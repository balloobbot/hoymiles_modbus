"""End to end tests against a DTU that misreports the data size of its responses."""

import asyncio
import struct

import pytest
from modbus_connection import ModbusError, ModbusTcpParams
from modbus_connection.pymodbus import ModbusConnection

from hoymiles_modbus.client import HoymilesDTU

from .test_hoymiles_modbus import (
    example_dtu_serial_number_raw_data,
    example_mi_series_raw_data,
    expected_mi_series_inverter,
    null_inverter_raw_data,
)

MBAP_HEADER_SIZE = 7
READ_HOLDING_REGISTERS = 3

INVERTER_BASE_ADDRESS = 0x1000
INVERTER_ADDRESS_STRIDE = 40
DTU_SERIAL_NUMBER_ADDRESS = 0x2000


class FakeDTU:
    """A DTU that answers reads with a deliberately wrong data size byte.

    Real DTUs send a data size that disagrees with the payload their MBAP header
    delimits; `declared_size` reproduces that so the workaround is exercised over an
    actual socket rather than against a decoder in isolation.
    """

    def __init__(self, declared_size):
        """Initialize the DTU, sizing its responses with `declared_size`."""
        self._declared_size = declared_size
        self._blocks = {
            INVERTER_BASE_ADDRESS: example_mi_series_raw_data,
            INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE: null_inverter_raw_data,
            DTU_SERIAL_NUMBER_ADDRESS: example_dtu_serial_number_raw_data,
        }
        self._server = None
        self._writers = set()

    @property
    def port(self):
        """Port the DTU listens on."""
        return self._server.sockets[0].getsockname()[1]

    async def start(self):
        """Start listening on a free port."""
        self._server = await asyncio.start_server(self._handle, '127.0.0.1', 0)

    async def stop(self):
        """Stop listening and drop any client still connected.

        `wait_closed` only returns once every handler has finished, so the clients have
        to be hung up on here rather than left waiting for a request that never comes.
        """
        for writer in self._writers:
            writer.close()
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader, writer):
        self._writers.add(writer)
        try:
            while request := await reader.readexactly(MBAP_HEADER_SIZE + 5):
                transaction_id, _, _, unit_id, _, address, _ = struct.unpack('>HHHBBHH', request)
                data = self._blocks[address]
                payload = struct.pack('>BB', READ_HOLDING_REGISTERS, self._declared_size(data)) + data
                writer.write(struct.pack('>HHHB', transaction_id, 0, len(payload) + 1, unit_id) + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()


@pytest.fixture
async def dtu_connection(request):
    """Connect to a fake DTU declaring its data size as the parameter says."""
    dtu = FakeDTU(request.param)
    await dtu.start()
    connection = ModbusConnection(ModbusTcpParams(host='127.0.0.1', port=dtu.port))
    try:
        yield connection
    finally:
        await connection.close()
        await dtu.stop()


@pytest.mark.parametrize(
    'dtu_connection',
    [
        pytest.param(len, id='correct data size'),
        pytest.param(lambda data: 0xFF, id='data size far too large'),
        pytest.param(lambda data: len(data) * 2, id='data size twice the payload'),
        pytest.param(lambda data: 0, id='data size zero'),
    ],
    indirect=True,
)
async def test_reads_a_dtu_that_misreports_data_size(dtu_connection):
    """Verify that inverter and DTU data decode whatever data size the DTU declares."""
    device = HoymilesDTU(dtu_connection.for_unit(1))
    await device.async_update()

    assert device.dtu == '11d361600831'
    assert device.inverters == [expected_mi_series_inverter]
    assert device.plant_data.today_production == 751


async def test_stock_connection_cannot_read_such_a_dtu():
    """Verify that the workaround is what makes the DTU readable at all."""
    dtu = FakeDTU(lambda data: 0xFF)
    await dtu.start()
    connection = ModbusConnection(ModbusTcpParams(host='127.0.0.1', port=dtu.port), timeout=1)
    try:
        with pytest.raises(ModbusError):
            await connection.for_unit(1).read_holding_registers(DTU_SERIAL_NUMBER_ADDRESS, 3)
    finally:
        await connection.close()
        await dtu.stop()
