"""The Deye Modbus integration."""
from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, CONF_UNIT_ID, CONF_SCAN_INTERVAL, CONF_MODEL, DEFAULT_SCAN_SECONDS,
    DEFAULT_PORT, DEFAULT_UNIT_ID,
    CONF_TRANSPORT, DEFAULT_TRANSPORT, CONF_BAUDRATE, DEFAULT_BAUDRATE,
    CONF_BYTESIZE, DEFAULT_BYTESIZE, CONF_PARITY, DEFAULT_PARITY,
    CONF_STOPBITS, DEFAULT_STOPBITS, CONF_ADDR_OFFSET, DEFAULT_ADDR_OFFSET,
    MIN_SCAN_SECONDS, MAX_SCAN_SECONDS, CONF_ALLOW_WRITES, DEFAULT_ALLOW_WRITES,
)
from .coordinator import DeyeModbusCoordinator, RegisterDef
from .mapping import load_register_mapping

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]
CONTROL_PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.TIME]
SUPPORTED_CONTROL_TYPES = {"number", "select", "switch", "time"}

# This integration is set up only via the UI config flow (no YAML config).
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Fields accepted by RegisterDef - anything else in the YAML is ignored.
_REGISTER_FIELDS = {
    "name", "unique_id", "register_type", "address", "second_address","count", "scale", "offset",
    "unit_of_measurement", "device_class", "state_class", "signed", "word_order",
    "options", "mask", "icon", "enabled_default", "precision", "slow",
}


def _ensure_uid(base: str | None, prefix: str, address: int) -> str:
    base = (base or "").strip()
    return base if base else f"{prefix}_{address}"


def _auto_inject_readbacks(sensors: list[dict], controls: list[dict]) -> tuple[list[dict], list[dict]]:
    """Give every writable control a hidden holding sensor to read its state back."""
    for s in sensors:
        s["unique_id"] = _ensure_uid(s.get("unique_id"), "s", int(s.get("address", 0)))
    sensor_uids = {s["unique_id"] for s in sensors}
    for c in controls:
        addr = c.get("address", c.get("base_address", 0))
        c["unique_id"] = _ensure_uid(c.get("unique_id"), c.get("type", "c"), int(addr))
        if c.get("type") in ("select32", "number32"):
            rb_uid = c.get("read_unique_id") or f"rb_{c['unique_id']}"
            if rb_uid not in sensor_uids:
                sensors.append({
                    "name": f"RB {c.get('name', c['unique_id'])}",
                    "unique_id": rb_uid, "register_type": "holding",
                    "address": int(c["base_address"]), "count": 2, "scale": 1.0,
                    "enabled_default": False,
                })
                sensor_uids.add(rb_uid)
            c["read_unique_id"] = rb_uid
            continue
        if not addr:
            continue
        if not c.get("read_unique_id"):
            rb_uid = f"rb_{c['unique_id']}"
            if rb_uid not in sensor_uids:
                sensors.append({
                    "name": f"RB {c.get('name', c['unique_id'])}",
                    "unique_id": rb_uid, "register_type": "holding",
                    "address": int(addr), "count": 1, "scale": 1.0,
                    "enabled_default": False, "slow": True,
                })
                sensor_uids.add(rb_uid)
            c["read_unique_id"] = rb_uid
            c.setdefault("read_factor", 1.0)
    return sensors, controls


def control_raw_range(c: dict) -> tuple[int, int]:
    """Raw register range a control may write, used for the coordinator allowlist."""
    t = c.get("type")
    if t == "number":
        f = float(c.get("write_factor", 1.0))
        return int(round(float(c["min"]) * f)), int(round(float(c["max"]) * f))
    if t == "time":
        return 0, 2359
    if "mask" in c:  # bit fields are read-modify-write: other bits are preserved
        return 0, 0xFFFF
    if t == "select":
        vals = [int(o["value"]) for o in c.get("options", [])]
        return min(vals), max(vals)
    if t == "switch":
        vals = (int(c.get("on_value", 1)), int(c.get("off_value", 0)))
        return min(vals), max(vals)
    raise ValueError(f"Unsupported control type {t!r}")


def build_allowlist(controls: list[dict]) -> dict[int, tuple[int, int]]:
    allow: dict[int, tuple[int, int]] = {}
    for c in controls:
        allow[int(c["address"])] = control_raw_range(c)
    return allow


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit_id = entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
    model_key = entry.data.get(CONF_MODEL)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_SECONDS))
    scan_interval = max(MIN_SCAN_SECONDS, min(MAX_SCAN_SECONDS, int(scan_interval)))
    transport = entry.options.get(CONF_TRANSPORT, entry.data.get(CONF_TRANSPORT, DEFAULT_TRANSPORT))
    addr_offset = entry.options.get(CONF_ADDR_OFFSET, DEFAULT_ADDR_OFFSET)
    serial_params = {
        "baudrate": entry.options.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
        "bytesize": entry.options.get(CONF_BYTESIZE, DEFAULT_BYTESIZE),
        "parity": entry.options.get(CONF_PARITY, DEFAULT_PARITY),
        "stopbits": entry.options.get(CONF_STOPBITS, DEFAULT_STOPBITS),
    }

    allow_writes = bool(entry.options.get(CONF_ALLOW_WRITES, DEFAULT_ALLOW_WRITES))

    mapping = await hass.async_add_executor_job(load_register_mapping, model_key)
    sensors_cfg = list(mapping.get("sensors", []))
    controls_cfg = list(mapping.get("controls", []))
    # Controls are only loaded when the user enabled writes AND the map says its
    # control addresses were verified on real hardware.
    if not (allow_writes and mapping.get("writes_supported")):
        if allow_writes:
            _LOGGER.warning("Writes enabled, but the %s map has no verified controls", model_key)
        controls_cfg = []
    controls_cfg = [c for c in controls_cfg if c.get("type") in SUPPORTED_CONTROL_TYPES]
    sensors_cfg, controls_cfg = _auto_inject_readbacks(sensors_cfg, controls_cfg)
    _LOGGER.info("Deye map path: %s (%s sensors, %s controls)",
                 mapping.get("path"), len(sensors_cfg), len(controls_cfg))

    registers = [
        RegisterDef(**{k: v for k, v in r.items() if k in _REGISTER_FIELDS})
        for r in sensors_cfg
    ]
    coordinator = DeyeModbusCoordinator(
        hass, host, port, unit_id, registers, scan_interval,
        transport=transport, serial_params=serial_params, address_offset=addr_offset,
    )
    coordinator.configure_writes(bool(controls_cfg), build_allowlist(controls_cfg))
    platforms = PLATFORMS + (CONTROL_PLATFORMS if controls_cfg else [])
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator, "registers": registers,
        "controls": controls_cfg, "model": model_key, "platforms": platforms,
    }
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DeyeModbusCoordinator = data["coordinator"]
    await coordinator.async_close()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, data.get("platforms", PLATFORMS))
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
