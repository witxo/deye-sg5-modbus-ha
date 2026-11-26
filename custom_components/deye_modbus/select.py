"""Select platform - holding-register values (or bit fields) as named options."""
from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .control_entity import DeyeControlEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    peers = {c["unique_id"]: c["read_unique_id"] for c in data["controls"]}
    entities = [DeyeModbusSelect(data["coordinator"], entry, c, peers)
                for c in data["controls"] if c.get("type") == "select"]
    if entities:
        async_add_entities(entities)


class DeyeModbusSelect(DeyeControlEntity, SelectEntity):
    def __init__(self, coordinator, entry, cfg: dict[str, Any], peers) -> None:
        super().__init__(coordinator, entry, cfg, peers)
        opts = cfg.get("options", [])
        self._value_by_label = {o["label"]: int(o["value"]) for o in opts}
        self._label_by_value = {int(o["value"]): o["label"] for o in opts}
        self._attr_options = list(self._value_by_label)

    @property
    def current_option(self) -> str | None:
        raw = self._raw()
        return None if raw is None else self._label_by_value.get(raw)

    async def async_select_option(self, option: str) -> None:
        if option not in self._value_by_label:
            raise HomeAssistantError(f"Unknown option {option!r}")
        await self._write_raw(self._value_by_label[option])
