"""Number platform - writable holding registers (currents, SOC, power)."""
from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .control_entity import DeyeControlEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    peers = {c["unique_id"]: c["read_unique_id"] for c in data["controls"]}
    entities = [DeyeModbusNumber(data["coordinator"], entry, c, peers)
                for c in data["controls"] if c.get("type") == "number"]
    if entities:
        async_add_entities(entities)


class DeyeModbusNumber(DeyeControlEntity, NumberEntity):
    def __init__(self, coordinator, entry, cfg: dict[str, Any], peers) -> None:
        super().__init__(coordinator, entry, cfg, peers)
        self._attr_native_min_value = float(cfg["min"])
        self._attr_native_max_value = float(cfg["max"])
        self._attr_native_step = float(cfg.get("step", 1))
        self._attr_mode = NumberMode.SLIDER if cfg.get("mode") == "slider" else NumberMode.BOX
        self._attr_native_unit_of_measurement = cfg.get("unit_of_measurement")
        if cfg.get("device_class"):
            self._attr_device_class = cfg["device_class"]
        self._factor = float(cfg.get("write_factor", 1.0))

    @property
    def native_value(self) -> float | None:
        raw = self._raw()
        return None if raw is None else raw / self._factor

    async def async_set_native_value(self, value: float) -> None:
        step = self._attr_native_step or 1.0
        v = max(self._attr_native_min_value, min(self._attr_native_max_value, round(value / step) * step))
        await self._write_raw(int(round(v * self._factor)))
