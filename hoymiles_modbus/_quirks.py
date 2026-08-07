"""Workarounds for protocol deviations of Hoymiles DTUs."""

from typing import TYPE_CHECKING

from modbus_connection.pymodbus import ModbusConnection as PymodbusConnection
from pymodbus.pdu.register_message import ReadHoldingRegistersResponse

if TYPE_CHECKING:  # pragma: no cover
    from modbus_connection import ModbusUnit


class _CustomReadHoldingRegistersResponse(ReadHoldingRegistersResponse):

    @staticmethod
    def _data_size_fixer(packet: bytes):
        fixed_packet = list(packet)
        fixed_packet[0] = len(fixed_packet[1:])  # calculate new data size
        return bytes(fixed_packet)

    def decode(self, data: bytes):
        fixed = self._data_size_fixer(data)
        return super().decode(fixed)


async def apply_dtu_quirks(unit: 'ModbusUnit') -> None:
    """Make the connection behind `unit` tolerate DTU responses with a wrong data size.

    Some DTUs send responses whose data size byte disagrees with the payload the MBAP
    header delimits. The framed payload is what actually arrived, so a custom PDU class
    recalculates the data size from it instead of trusting the declared value.

    Only the pymodbus backend can be adjusted this way, so units from other backends are
    left alone. Registering is per decoder instance, and a reconnect builds a fresh
    client, hence the check on every call.

    Arguments:
        unit: unit to adjust the underlying connection of

    """
    connection = getattr(unit, '_conn', None)
    if not isinstance(connection, PymodbusConnection):
        return

    await connection.connect()
    decoder = connection._client.ctx.framer.decoder
    if decoder.pdu_table[_CustomReadHoldingRegistersResponse.function_code][decoder.pdu_inx] is not (
        _CustomReadHoldingRegistersResponse
    ):
        decoder.register(_CustomReadHoldingRegistersResponse)
