"""Errors raised by this library.

Communication failures surface as `modbus_connection.ModbusError` subclasses and are
left alone. These cover the DTU answering with something the library cannot make sense
of, which is a state of the installation rather than a fault of the link.

They derive from `RuntimeError`, which is what the library raised before they existed.
"""


class HoymilesModbusError(RuntimeError):
    """Base class for errors raised by this library."""


class InvertersNotMappedError(HoymilesModbusError):
    """The DTU answered, but has no inverters mapped yet.

    Inverters have to be added to the DTU before it serves any data for them.
    """


class InverterDataError(HoymilesModbusError):
    """The DTU answered with data that could not be decoded.

    A DTU sending fewer bytes than its own data size byte claims is a known failure of
    these devices, and one the data size workaround cannot repair - it makes the
    response decodable as Modbus registers, not complete.
    """
