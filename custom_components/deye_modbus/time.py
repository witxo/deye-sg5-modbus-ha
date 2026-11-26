"""Time platform - Deye time-of-use slot start times stored as HHMM (e.g. 2230)."""
from __future__ import annotations
from datetime import time as dt_time
from typing import Any
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .control_entity import DeyeControlEntity

_LOGGER = logging.getLogger(__name__)


def hhmm_to_time(raw: int) -> dt_time | None:
    h, m = divmod(int(raw), 100)
    if 0 <= h <= 23 and 0 <= m <= 59:
        return dt_time(h, m)
    return None


def time_to_hhmm(value: dt_time) -> int:
    return value.hour * 100 + value.minute


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    peers = {c["unique_id"]: c["read_unique_id"] for c in data["controls"]}
    entities = [DeyeModbusTime(data["coordinator"], entry, c, peers)
                for c in data["controls"] if c.get("type") == "time"]
    if entities:
        async_add_entities(entities)


class DeyeModbusTime(DeyeControlEntity, TimeEntity):
    def __init__(self, coordinator, entry, cfg: dict[str, Any], peers) -> None:
        super().__init__(coordinator, entry, cfg, peers)

    @property
    def native_value(self) -> dt_time | None:
        raw = self._raw()
        return None if raw is None else hhmm_to_time(raw)

    async def async_set_value(self, value: dt_time) -> None:
        await self._write_raw(time_to_hhmm(value))
