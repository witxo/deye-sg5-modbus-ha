"""DataUpdateCoordinator that polls a Deye hybrid inverter over Modbus.

Deye three-phase hybrid inverters expose *all* live measurements through the
holding-register space (function code 0x03), including the 500+ real-time block.
Unlike some vendors there is no separate "read once" settings space here, so
every mapped register is polled each cycle. Contiguous registers are batched
into single Modbus reads to keep the poll cheap.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

WRITE_COOLDOWN_S = 30          # minimum seconds between writes to one register
SLOW_POLL_EVERY = 4            # settings registers are read every Nth poll


class WriteRejected(HomeAssistantError):
    """A write was refused by a safety check before reaching the inverter."""


class WriteFailed(HomeAssistantError):
    """The inverter did not accept or did not keep the written value."""


try:
    from pymodbus.client import AsyncModbusTcpClient, AsyncModbusSerialClient
except Exception as exc:  # pragma: no cover
    _LOGGER.error("pymodbus import failed: %s", exc)
    raise


@dataclass
class RegisterDef:
    """One decoded value read from the inverter."""

    name: str
    unique_id: str
    register_type: str = "holding"           # "holding" (0x03) or "input" (0x04)
    address: int = 0
    second_address: int | None = None        # Optional second word for non contiguous 32-bit values
    count: int = 1                           # 1 = 16-bit, 2 = 32-bit
    scale: float = 1.0
    offset: float = 0.0                      # raw is (value - offset) before scaling
    unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    signed: bool = False
    word_order: str = "high_low"             # 32-bit word order: high_low | low_high
    options: dict[int, str] | None = None    # enum mapping for sensors (0 -> "text")
    mask: int | None = None                  # bitmask applied to raw before sign/scale
    icon: str | None = None
    enabled_default: bool = True             # entity_registry_enabled_default
    precision: int | None = None             # suggested_display_precision (decimals)
    slow: bool = False                       # settings register: read every SLOW_POLL_EVERY polls


class DeyeModbusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all mapped registers each cycle and decodes them."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        unit_id: int,
        registers: List[RegisterDef],
        scan_interval: int,
        transport: str = "tcp",
        serial_params: dict | None = None,
        address_offset: int = 0,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name="deye_modbus coordinator",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._host, self._port, self._unit_id = host, port, int(unit_id)
        self._registers: List[RegisterDef] = registers
        self._transport = (transport or "tcp").lower()
        self._serial_params = serial_params or {}
        self._client = None
        self._lock = asyncio.Lock()
        self._addr_off = int(address_offset or 0)
        self._writes_enabled = False
        self._allowlist: dict[int, tuple[int, int]] = {}
        self._last_write: dict[int, float] = {}
        self._poll_count = 0
        self._force_slow = True
        self._slow_cache: dict[str, Any] = {}

    def _addr(self, addr: int) -> int:
        return int(addr) - self._addr_off if self._addr_off else int(addr)

    # ------------------------------------------------------------------ client
    async def _ensure_client(self):
        if self._client is None:
            if self._transport == "rtutcp":
                url = f"socket://{self._host}:{self._port}"
                params = {
                    #"method": "rtu", "port": url, #fix: rtutcp setup with newer pymodbus by removing deprecated method kwarg
                    "port": url,
                    "baudrate": int(self._serial_params.get("baudrate", 9600)),
                    "bytesize": int(self._serial_params.get("bytesize", 8)),
                    "parity": str(self._serial_params.get("parity", "N")),
                    "stopbits": int(self._serial_params.get("stopbits", 1)),
                    "timeout": 5,
                }
                self._client = AsyncModbusSerialClient(**params)
            else:
                try:
                    self._client = AsyncModbusTcpClient(self._host, port=self._port, timeout=5)
                except TypeError:
                    self._client = AsyncModbusTcpClient(self._host, port=self._port)
        if not bool(getattr(self._client, "connected", False)):
            try:
                await self._client.connect()
            except Exception as e:  # noqa: BLE001
                raise UpdateFailed(f"Modbus connect failed: {e}") from e
        return self._client

    # ------------------------------------------------------------------ polling
    async def _async_update_data(self) -> dict[str, Any]:
        async with self._lock:
            try:
                result: dict[str, Any] = {}
                read_slow = self._force_slow or self._poll_count % SLOW_POLL_EVERY == 0
                self._poll_count += 1
                regs = [r for r in self._registers if read_slow or not r.slow]
                inputs = [r for r in regs if r.register_type == "input"]
                holdings = [r for r in regs if r.register_type != "input"]
                if holdings:
                    await self._read_grouped(holdings, result, self._read_holding)
                if inputs:
                    await self._read_grouped(inputs, result, self._read_input)
                if read_slow:
                    self._force_slow = False
                    self._slow_cache = {r.unique_id: result.get(r.unique_id) for r in regs if r.slow}
                else:
                    result.update(self._slow_cache)
                return result
            except Exception as err:  # noqa: BLE001
                raise UpdateFailed(err) from err


    async def _read_grouped(self, regs: list[RegisterDef], out: dict[str, Any], fn):
        # Read non-contiguous registers separately.
        special = [r for r in regs if r.second_address is not None]
        regular = [r for r in regs if r.second_address is None]

        for r in special:
            if r.count != 2:
                raise ValueError(
                    f"{r.name}: second_address requires count: 2"
                )

            first = await fn(r.address, 1)
            second = await fn(r.second_address, 1)

            if first is None or second is None or len(first) < 1 or len(second) < 1:
                out[r.unique_id] = None
            else:
                out[r.unique_id] = self._decode(
                    r, [first[0], second[0]], r.address
                )

        # Normal contiguous registers retain the existing grouped-read logic.
        regs = sorted(regular, key=lambda r: r.address)
        GAP = 0
        MAX_WORDS = 5
        start = end = None
        acc: list[RegisterDef] = []

        for r in regs:
            if start is None:
                start, end, acc = r.address, r.address + r.count, [r]
                continue

            if r.address <= end + GAP and (r.address + r.count - start) <= MAX_WORDS:
                end = max(end, r.address + r.count)
                acc.append(r)
            else:
                await self._read_window(fn, out, start, end, acc)
                start, end, acc = r.address, r.address + r.count, [r]

        if start is not None:
            await self._read_window(fn, out, start, end, acc)


    async def _read_window(self, fn, out, start, end, regs):
        raw = await fn(self._addr(start), end - start)
        for r in regs:
            out[r.unique_id] = self._decode(r, raw, start)

    def _decode(self, r: RegisterDef, raw, start) -> Any:
        if not raw:
            return None
        
        if r.second_address is not None:
            chunk = raw[:2]
        else:
            off = r.address - start
            chunk = raw[off:off + r.count]

        if len(chunk) < r.count:
            return None
        if r.count == 1:
            v = chunk[0]
            if r.mask is not None:
                v &= r.mask
            if r.signed and v >= 0x8000:
                v -= 0x10000
            return (v - r.offset) * r.scale
        if r.count == 2:
            if r.word_order == "low_high":
                low, high = chunk[0], chunk[1]
            else:
                high, low = chunk[0], chunk[1]
            v = (high << 16) | low
            if r.mask is not None:
                v &= r.mask
            if r.signed and v >= 0x80000000:
                v -= 0x100000000
            return (v - r.offset) * r.scale
        return None

    # ------------------------------------------------------------------ reads
    async def _call_read(self, method_name, address, count):
        client = await self._ensure_client()
        method = getattr(client, method_name)
        a = self._addr(address)
        # pymodbus 3.x -> slave=, pymodbus 2.x -> unit=, older -> positional.
        for kwargs in (
            {"count": count, "slave": self._unit_id},
            {"count": count, "device_id": self._unit_id},
            {"count": count, "unit": self._unit_id},
            {"count": count},
        ):
            try:
                return await method(a, **kwargs)
            except TypeError:
                continue
        try:
            return await method(a, count)
        except TypeError:
            return None

    async def _read_input(self, address, count):
        rr = await self._call_read("read_input_registers", address, count)
        return None if rr is None or (getattr(rr, "isError", None) and rr.isError()) else getattr(rr, "registers", None)

    async def _read_holding(self, address, count):
        rr = await self._call_read("read_holding_registers", address, count)
        return None if rr is None or (getattr(rr, "isError", None) and rr.isError()) else getattr(rr, "registers", None)

    # ------------------------------------------------------------------ writes
    #
    # Writes are guarded in layers, all enforced here so no entity or service can
    # bypass them:
    #   1. writes must be enabled for the config entry (option, off by default);
    #   2. the address must be in the allowlist built from the map's controls,
    #      and the raw value must be inside that control's raw range;
    #   3. one write per register per WRITE_COOLDOWN_S;
    #   4. a write is skipped when the register already holds the value;
    #   5. after writing, the register is read back and compared.
    # Deye inverters only accept FC16 (write multiple registers), so every
    # write uses FC16, even for a single register.

    def configure_writes(self, enabled: bool, allowlist: dict[int, tuple[int, int]]) -> None:
        """Enable writes and set {address: (raw_min, raw_max)}."""
        self._writes_enabled = bool(enabled)
        self._allowlist = dict(allowlist)

    def _check_allowed(self, address: int, value: int) -> None:
        if not getattr(self, "_writes_enabled", False):
            raise WriteRejected("Writes are disabled for this inverter (enable them in the integration options)")
        allow = getattr(self, "_allowlist", {})
        if address not in allow:
            raise WriteRejected(f"Register {address} is not a writable control in this map")
        lo, hi = allow[address]
        if not lo <= value <= hi:
            raise WriteRejected(f"Value {value} for register {address} is outside {lo}..{hi}")

    def _check_cooldown(self, address: int) -> None:
        last = self._last_write.get(address)
        now = time.monotonic()
        if last is not None and now - last < WRITE_COOLDOWN_S:
            wait = int(WRITE_COOLDOWN_S - (now - last)) + 1
            raise WriteRejected(f"Register {address} was changed less than {WRITE_COOLDOWN_S}s ago; try again in {wait}s")

    async def _call_write(self, address: int, values: list[int]):
        client = await self._ensure_client()
        a = self._addr(address)
        for kwargs in ({"slave": self._unit_id}, {"device_id": self._unit_id}, {"unit": self._unit_id}):
            try:
                return await client.write_registers(a, values, **kwargs)
            except TypeError:
                continue
        return await client.write_registers(a, values)

    async def write_single_register(self, address: int, value: int) -> bool:
        """Write one holding register (via FC16) with all safety checks.

        Returns True when the value was written and verified (or was already
        set). Raises WriteRejected / WriteFailed otherwise.
        """
        address, value = int(address), int(value)
        self._check_allowed(address, value)
        async with self._lock:
            current = await self._read_holding(address, 1)
            if current and current[0] == value:
                _LOGGER.debug("Register %s already holds %s, not writing", address, value)
                return True
            self._check_cooldown(address)
            old = current[0] if current else None
            try:
                rr = await self._call_write(address, [value])
            except Exception as err:  # noqa: BLE001
                raise WriteFailed(f"Modbus write to register {address} failed: {err}") from err
            self._last_write[address] = time.monotonic()
            if rr is None or (getattr(rr, "isError", None) and rr.isError()):
                raise WriteFailed(f"Inverter rejected write to register {address}: {rr}")
            await asyncio.sleep(0.3)
            check = await self._read_holding(address, 1)
            if not check or check[0] != value:
                got = check[0] if check else None
                _LOGGER.error("Write verify failed for register %s: wrote %s, read back %s", address, value, got)
                raise WriteFailed(f"Register {address}: wrote {value} but inverter reports {got}")
            _LOGGER.warning("Deye register %s changed %s -> %s", address, old, value)
        self._force_slow = True
        return True

    async def write_bits(self, address: int, mask: int, bits: int) -> bool:
        """Read-modify-write: change only the bits in mask, keep the rest."""
        async with self._lock:
            current = await self._read_holding(address, 1)
        if not current:
            raise WriteFailed(f"Could not read register {address} before changing its bits")
        new = (current[0] & ~mask & 0xFFFF) | (bits & mask)
        return await self.write_single_register(address, new)

    async def write_multiple_registers(self, address: int, values: list[int]) -> bool:
        raise WriteRejected("Multi-register writes are not supported")

    async def write_u32(self, base_address: int, value: int, word_order: str = "high_low") -> bool:
        raise WriteRejected("32-bit writes are not supported")

    async def write_coil(self, address: int, value: int) -> bool:
        raise WriteRejected("Coil writes are not supported on Deye")

    async def async_close(self):
        try:
            if self._client:
                await self._client.close()
        except Exception:  # noqa: BLE001
            pass
