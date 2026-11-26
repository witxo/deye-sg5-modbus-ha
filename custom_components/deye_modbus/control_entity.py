"""Shared base for writable Deye controls (number / select / switch / time)."""
from __future__ import annotations
from typing import Any, Optional
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DeyeModbusCoordinator
from .device_helper import build_device_info

_LOGGER = logging.getLogger(__name__)


def mask_shift(mask: int) -> int:
    """Position of the lowest set bit of mask."""
    return (mask & -mask).bit_length() - 1 if mask else 0


class DeyeControlEntity(CoordinatorEntity[dict[str, Any]]):
    """Holds the register config, the read-back value and cross-field checks.

    YAML keys used here:
      address, name, unique_id, icon, entity_category, enabled_default
      read_unique_id   hidden sensor that reads the register back (auto-injected)
      mask             optional bit mask; writes become read-modify-write
      less_than / greater_than   unique_id of another control whose current raw
                       value this control's raw value must stay below / above
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DeyeModbusCoordinator, entry: ConfigEntry, cfg: dict[str, Any],
                 peers: dict[str, str]) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._cfg = cfg
        self._address = int(cfg["address"])
        self._mask: Optional[int] = int(str(cfg["mask"]), 0) if "mask" in cfg else None
        self._shift = mask_shift(self._mask) if self._mask else 0
        self._read_uid: str = cfg["read_unique_id"]
        self._peers = peers  # control unique_id -> read-back unique_id
        self._attr_name = cfg.get("name")
        self._attr_unique_id = f"{entry.entry_id}_{cfg['unique_id']}"
        self._attr_device_info = build_device_info(entry)
        self._attr_entity_registry_enabled_default = bool(cfg.get("enabled_default", True))
        if cfg.get("icon"):
            self._attr_icon = cfg["icon"]
        ec = cfg.get("entity_category", "config")
        try:
            self._attr_entity_category = EntityCategory(ec)
        except ValueError:
            _LOGGER.warning("Unknown entity_category %r for %s", ec, self._attr_name)

    # ----------------------------------------------------------------- reading
    def _raw_of(self, read_uid: str) -> Optional[int]:
        v = (self.coordinator.data or {}).get(read_uid)
        if v is None:
            return None
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None

    def _raw(self) -> Optional[int]:
        """Current register value, reduced to the masked field if any."""
        raw = self._raw_of(self._read_uid)
        if raw is None or self._mask is None:
            return raw
        return (raw & self._mask) >> self._shift

    @property
    def available(self) -> bool:
        return super().available and self._raw() is not None

    # ----------------------------------------------------------------- writing
    def _check_peers(self, raw: int) -> None:
        for key, ok, word in (("less_than", lambda a, b: a < b, "below"),
                              ("greater_than", lambda a, b: a > b, "above")):
            peer = self._cfg.get(key)
            if not peer:
                continue
            peer_uid = self._peers.get(peer)
            other = self._raw_of(peer_uid) if peer_uid else None
            if other is None:
                raise HomeAssistantError(f"{self.name}: cannot check against {peer} (value unknown)")
            if not ok(raw, other):
                raise HomeAssistantError(f"{self.name}: value must stay {word} {peer} ({other})")

    async def _write_raw(self, raw: int) -> None:
        self._check_peers(raw)
        if self._mask is None:
            await self._coordinator.write_single_register(self._address, raw)
        else:
            await self._coordinator.write_bits(self._address, self._mask, raw << self._shift)
        await self._coordinator.async_request_refresh()
