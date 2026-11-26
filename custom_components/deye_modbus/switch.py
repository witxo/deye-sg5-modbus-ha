"""Switch platform - on/off holding registers (or single bits)."""
from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .control_entity import DeyeControlEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    peers = {c["unique_id"]: c["read_unique_id"] for c in data["controls"]}
    entities = [DeyeModbusSwitch(data["coordinator"], entry, c, peers)
                for c in data["controls"] if c.get("type") == "switch"]
    if entities:
        async_add_entities(entities)


class DeyeModbusSwitch(DeyeControlEntity, SwitchEntity):
    def __init__(self, coordinator, entry, cfg: dict[str, Any], peers) -> None:
        super().__init__(coordinator, entry, cfg, peers)
        self._on = int(cfg.get("on_value", 1))
        self._off = int(cfg.get("off_value", 0))

    @property
    def is_on(self) -> bool | None:
        raw = self._raw()
        return None if raw is None else raw == self._on

    async def async_turn_on(self, **kwargs) -> None:
        await self._write_raw(self._on)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write_raw(self._off)
