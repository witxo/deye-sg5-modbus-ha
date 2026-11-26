"""Test fixtures: a real Modbus TCP server holding a captured SG05LP1 register image."""
from __future__ import annotations
import asyncio
import json
import logging
import socket
from pathlib import Path

import pytest
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ModbusTcpServer

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

FIXTURE = Path(__file__).parent / "fixtures" / "sg05lp1_settings.json"


def load_image() -> list[int]:
    regs = json.loads(FIXTURE.read_text())["registers"]
    image = [0] * 400
    for k, v in regs.items():
        image[int(k)] = v
    return image


class FakeInverter(ModbusServerContext):
    """Server context backed by a plain register list (FC03 reads, FC16 writes).

    Addresses in `ignore_writes` acknowledge the write but keep their value,
    like an inverter that silently refuses a setting.
    """

    def __init__(self, values: list[int]) -> None:
        super().__init__(devices=ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, [0])), single=True)
        # make the server call our async_getValues/async_setValues directly
        self.simdevices = []
        self.old_simulator = True
        self.image = list(values)
        self.ignore_writes: set[int] = set()
        self.writes: list[tuple[int, list[int]]] = []
        self.port = 0

    async def async_getValues(self, device_id, func_code, address, count=1):  # noqa: N802
        return self.image[address:address + count]

    async def async_setValues(self, device_id, func_code, address, values):  # noqa: N802
        assert func_code == 16, f"Deye only accepts FC16, got FC{func_code}"
        self.writes.append((address, list(values)))
        if address in self.ignore_writes:
            return None
        self.image[address:address + len(values)] = list(values)
        return None

    def reg(self, address: int) -> int:
        return self.image[address]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def inverter(socket_enabled):
    block = FakeInverter(load_image())
    port = _free_port()
    server = ModbusTcpServer(block, address=("127.0.0.1", port))
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0.2)
    block.port = port
    yield block
    await server.shutdown()
    task.cancel()
