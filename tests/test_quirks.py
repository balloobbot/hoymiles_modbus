"""Tests for DTU quirk workarounds."""

import pytest
from modbus_connection import ModbusTcpParams
from modbus_connection.mock import MockModbusConnection
from modbus_connection.pymodbus import ModbusConnection

from hoymiles_modbus._quirks import _CustomReadHoldingRegistersResponse, apply_dtu_quirks

FUNCTION_CODE = _CustomReadHoldingRegistersResponse.function_code


@pytest.fixture
def connection(monkeypatch):
    """Build a pymodbus-backed connection whose client never reaches the network."""
    connection = ModbusConnection(ModbusTcpParams(host='127.0.0.1', port=502))

    async def connect(self):
        if self._client is None:
            self._client = await self._create_client()

    monkeypatch.setattr(type(connection), 'connect', connect)
    return connection


async def quirked_decoder(connection):
    """Apply the quirks to a connection and hand back the response decoder they landed on."""
    await apply_dtu_quirks(connection.for_unit(1))
    return connection._client.ctx.framer.decoder


def registered_response_class(decoder):
    """Return the response class the decoder resolves read holding registers to."""
    return decoder.pdu_table[FUNCTION_CODE][decoder.pdu_inx]


async def test_data_size_fixer(connection):
    """Verify PDU data size fixer."""
    decoder = await quirked_decoder(connection)
    # should be able to decode frame even with wrong size (0xFF here)
    pdu = decoder.decode(b'\x03\xff\x10\xf8q`\x081')
    assert pdu.registers[0] == 4344


async def test_fixer_with_empty_data(connection):
    """Verify data size fixer with empty data."""
    decoder = await quirked_decoder(connection)
    assert decoder.decode(b'\x03') is None


async def test_healthy_response_unaffected(connection):
    """Verify that a response with a correct data size still decodes."""
    decoder = await quirked_decoder(connection)
    assert decoder.decode(b'\x03\x06\x10\xf8q`\x081').registers == [4344, 29024, 2097]


async def test_oversized_response(connection):
    """Verify decoding a DTU response carrying more registers than were requested."""
    decoder = await quirked_decoder(connection)
    pdu = decoder.decode(b'\x03\x50' + b'\xab\xcd' * 40)
    assert len(pdu.registers) == 40


async def test_quirks_applied_only_once(connection):
    """Verify that re-applying the quirks does not stack response classes."""
    decoder = await quirked_decoder(connection)
    assert registered_response_class(decoder) is _CustomReadHoldingRegistersResponse
    assert await quirked_decoder(connection) is decoder
    assert registered_response_class(decoder) is _CustomReadHoldingRegistersResponse


async def test_quirks_reapplied_after_reconnect(connection):
    """Verify that a client built by a reconnect gets the custom response class too."""
    decoder = await quirked_decoder(connection)
    connection._client = None  # as a dropped link leaves it
    reconnected = await quirked_decoder(connection)
    assert reconnected is not decoder
    assert registered_response_class(reconnected) is _CustomReadHoldingRegistersResponse


async def test_stock_decoder_rejects_wrong_data_size(connection):
    """Verify that the workaround is what makes a wrong data size decodable."""
    await connection.connect()
    decoder = connection._client.ctx.framer.decoder
    assert decoder.decode(b'\x03\xff\x10\xf8q`\x081') is None


async def test_non_pymodbus_unit_is_left_alone():
    """Verify that a unit from another backend is not touched."""
    await apply_dtu_quirks(MockModbusConnection().for_unit(1))  # must not raise
