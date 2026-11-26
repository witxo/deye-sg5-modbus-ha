"""Write-path tests against a simulated SG05LP1 (real Modbus TCP, FC03/FC16)."""
from __future__ import annotations
from datetime import time as dt_time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_modbus import build_allowlist, control_raw_range
from custom_components.deye_modbus.const import DOMAIN
from custom_components.deye_modbus.coordinator import (
    DeyeModbusCoordinator, WriteFailed, WriteRejected,
)
from custom_components.deye_modbus.mapping import load_register_mapping
from custom_components.deye_modbus.time import hhmm_to_time, time_to_hhmm

MODEL = "sun_6k_sg05lp1_1ph"


# ---------------------------------------------------------------- map sanity
def test_map_controls_stay_in_settings_block():
    m = load_register_mapping(MODEL)
    assert m["writes_supported"] is True
    addrs = {int(c["address"]) for c in m["controls"]}
    assert addrs <= set(range(210, 280))
    # battery type / voltages and device registers are never writable
    assert not addrs & {200, 201, 202, 203, 204, 205, 213}
    # GEN port mode is writable but its entity is disabled by default
    gen_mode = next(c for c in m["controls"] if c["unique_id"] == "gen_port_mode")
    assert gen_mode["enabled_default"] is False


def test_three_phase_map_has_no_verified_writes():
    assert load_register_mapping("sun12k_sg05lp3")["writes_supported"] is False


def test_raw_ranges():
    assert control_raw_range({"type": "number", "min": 0, "max": 135}) == (0, 135)
    assert control_raw_range({"type": "time"}) == (0, 2359)
    assert control_raw_range({"type": "switch", "mask": 1}) == (0, 0xFFFF)
    allow = build_allowlist(load_register_mapping(MODEL)["controls"])
    assert allow[244] == (0, 2)
    assert allow[245] == (0, 6000)


def test_hhmm():
    assert hhmm_to_time(2130) == dt_time(21, 30)
    assert hhmm_to_time(2460) is None
    assert time_to_hhmm(dt_time(5, 5)) == 505


# ---------------------------------------------------------------- coordinator
def _coordinator(hass, inverter, enabled=True):
    c = DeyeModbusCoordinator(hass, "127.0.0.1", inverter.port, 1, [], 15)
    c.configure_writes(enabled, {211: (0, 135), 244: (0, 2), 248: (0, 0xFFFF)})
    return c


async def test_writes_disabled(hass: HomeAssistant, inverter):
    c = _coordinator(hass, inverter, enabled=False)
    with pytest.raises(WriteRejected):
        await c.write_single_register(211, 100)
    assert inverter.writes == []
    await c.async_close()


async def test_not_allowlisted_and_out_of_range(hass: HomeAssistant, inverter):
    c = _coordinator(hass, inverter)
    with pytest.raises(WriteRejected):
        await c.write_single_register(235, 0)      # GEN port mode
    with pytest.raises(WriteRejected):
        await c.write_single_register(211, 200)    # above 135 A
    assert inverter.writes == []
    await c.async_close()


async def test_write_verify_and_cooldown(hass: HomeAssistant, inverter):
    c = _coordinator(hass, inverter)
    assert await c.write_single_register(211, 100)
    assert inverter.reg(211) == 100
    assert inverter.writes == [(211, [100])]     # one FC16 write
    with pytest.raises(WriteRejected, match="less than"):
        await c.write_single_register(211, 99)
    # writing the value it already holds is a no-op, even during cooldown
    assert await c.write_single_register(211, 100)
    assert len(inverter.writes) == 1
    await c.async_close()


async def test_write_not_kept_raises(hass: HomeAssistant, inverter):
    inverter.ignore_writes.add(244)
    c = _coordinator(hass, inverter)
    with pytest.raises(WriteFailed, match="inverter reports 2"):
        await c.write_single_register(244, 0)
    await c.async_close()


async def test_bits_preserve_other_bits(hass: HomeAssistant, inverter):
    c = _coordinator(hass, inverter)
    assert inverter.reg(248) == 255
    await c.write_bits(248, 0x0001, 0)
    assert inverter.reg(248) == 254   # TOU off, weekday bits kept
    await c.async_close()


# ---------------------------------------------------------------- integration
async def _setup(hass, inverter, allow_writes: bool) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "127.0.0.1", "port": inverter.port, "unit_id": 1,
              "model": MODEL, "scan_interval": 15},
        options={"allow_writes": allow_writes},
        unique_id=f"127.0.0.1:{inverter.port}:1",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass, entry, platform, uid) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{uid}")
    assert eid, f"{platform}.{uid} missing"
    return eid


async def test_read_only_by_default(hass: HomeAssistant, inverter):
    await _setup(hass, inverter, allow_writes=False)
    for domain in ("number", "select", "switch", "time"):
        assert hass.states.async_entity_ids(domain) == []
    assert inverter.writes == []


@patch("custom_components.deye_modbus.coordinator.WRITE_COOLDOWN_S", 0)
async def test_entities_read_and_write(hass: HomeAssistant, inverter):
    entry = await _setup(hass, inverter, allow_writes=True)
    assert inverter.writes == []          # setup never writes

    work = _eid(hass, entry, "select", "work_mode")
    assert hass.states.get(work).state == "Zero Export To CT"
    assert hass.states.get(_eid(hass, entry, "number", "batt_max_charge_current")).state == "135.0"
    assert hass.states.get(_eid(hass, entry, "time", "tou6_time")).state == "21:00:00"
    assert hass.states.get(_eid(hass, entry, "switch", "tou1_grid_charge")).state == "off"

    await hass.services.async_call("number", "set_value", {
        "entity_id": _eid(hass, entry, "number", "batt_max_discharge_current"), "value": 99}, blocking=True)
    assert inverter.reg(211) == 99

    await hass.services.async_call("switch", "turn_on", {
        "entity_id": _eid(hass, entry, "switch", "tou1_grid_charge")}, blocking=True)
    assert inverter.reg(274) == 5     # bit 0 set, bit 2 kept

    await hass.services.async_call("time", "set_value", {
        "entity_id": _eid(hass, entry, "time", "tou2_time"), "time": "04:30:00"}, blocking=True)
    assert inverter.reg(251) == 430

    # GEN voltages are stored in 0.01 V
    gen_v = _eid(hass, entry, "number", "gen_charge_start_voltage")
    assert hass.states.get(gen_v).state == "49.0"
    await hass.services.async_call("number", "set_value", {"entity_id": gen_v, "value": 48.5}, blocking=True)
    assert inverter.reg(225) == 4850
    assert hass.states.get(_eid(hass, entry, "number", "gen_off_soc")).state == "100.0"

    # GEN port mode has no entity unless the user enables it
    reg_entry = er.async_get(hass).async_get(_eid(hass, entry, "select", "gen_port_mode"))
    assert reg_entry.disabled_by is not None

    # out-of-order TOU times and SOC thresholds are refused before any write
    n = len(inverter.writes)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("time", "set_value", {
            "entity_id": _eid(hass, entry, "time", "tou3_time"), "time": "03:00:00"}, blocking=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("number", "set_value", {
            "entity_id": _eid(hass, entry, "number", "batt_shutdown_soc"), "value": 30}, blocking=True)
    assert len(inverter.writes) == n
