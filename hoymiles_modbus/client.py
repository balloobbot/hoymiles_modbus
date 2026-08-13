"""Hoymiles Modbus client."""

from typing import TYPE_CHECKING, Optional

from modbus_connection import ModbusConnectionError, ModbusError, ModbusExceptionError, ReadBlock
from plum.exceptions import UnpackError

from ._quirks import apply_dtu_quirks
from .datatypes import InverterData, PlantData, UpdateReport, _serial_number_t
from .exceptions import InverterDataError, InvertersNotMappedError

if TYPE_CHECKING:  # pragma: no cover
    from modbus_connection import ModbusUnit


def _to_bytes(registers: list[int]) -> bytes:
    return b''.join(register.to_bytes(2, 'big') for register in registers)


async def _read_block(unit: 'ModbusUnit', address: int, count: int) -> list[int]:
    """Read holding registers, recording which block a refusal was about.

    A plant is read one block per inverter, so the exception code alone does not say
    which of them the DTU refused. The block is attached the way the device modelling
    layer attaches it, leaving the raised class untouched.
    """
    try:
        return await unit.read_holding_registers(address, count)
    except ModbusExceptionError as err:
        if err.block is None:
            err.block = ReadBlock('holding', address, count)
        raise


class HoymilesDTU:
    """Hoymiles DTU.

    Gather data from photovoltaic installation based on Hoymiles inverters managed by Hoymiles DTU (like DTU-pro).

    The DTU is addressed through a `ModbusUnit`, so the caller owns the connection and decides which backend
    and transport to use. A real DTU needs the pymodbus backend - see `hoymiles_modbus._quirks`.

    """

    _MAX_INVERTER_COUNT = 100
    _NULL_INVERTER = '000000000000'
    _INVERTER_BASE_ADDRESS = 0x1000
    _INVERTER_ADDRESS_STRIDE = 40
    _INVERTER_REGISTER_COUNT = 20
    _INVERTER_DATA_SIZE = 40
    _DTU_SERIAL_NUMBER_ADDRESS = 0x2000
    _DTU_SERIAL_NUMBER_REGISTER_COUNT = 3

    def __init__(self, unit: 'ModbusUnit') -> None:
        """Initialize the object.

        Arguments:
            unit: Modbus unit the DTU answers on

        """
        self._unit = unit
        self.dtu: str = ''
        """DTU serial number. Empty until the first update."""
        self.inverters: list[InverterData] = []
        """Status data from all inverters, as of the last update.

        An inverter whose block failed keeps the data of the update before it."""
        self.plant_data: Optional[PlantData] = None
        """Plant status data, as of the last update. `None` until the first update."""

    @classmethod
    async def async_probe(cls, unit: 'ModbusUnit') -> str:
        """Read the DTU serial number, without polling the inverters.

        Identifies the device during setup, when reading the whole plant would be premature.

        Arguments:
            unit: Modbus unit the DTU answers on

        """
        await apply_dtu_quirks(unit)
        registers = await _read_block(unit, cls._DTU_SERIAL_NUMBER_ADDRESS, cls._DTU_SERIAL_NUMBER_REGISTER_COUNT)
        try:
            return _serial_number_t.unpack(_to_bytes(registers))
        except UnpackError as err:
            raise InverterDataError(f'Could not decode the DTU serial number: {err.__class__.__name__}') from err

    async def async_update(self) -> UpdateReport:
        """Refresh all data with a new request to the installation.

        A plant is read one block per inverter, and the blocks are independent: an
        inverter whose block fails keeps the data of the update before while the rest
        still refresh, and the returned report names it with the error that failed it.
        A failure of the link itself raises `ModbusConnectionError` instead.

        The DTU serial number is read first and only once - it identifies the
        installation, so until it is known there is nothing to report against.
        """
        await apply_dtu_quirks(self._unit)
        if not self.dtu:
            self.dtu = await self.async_probe(self._unit)
        self.inverters, failed = await self._async_read_inverters()
        self.plant_data = self._calculate_plant_data()
        # A failed slot holds the inverter the previous update read, so what refreshed is
        # every serial number in the plant except the ones reported as failed.
        return UpdateReport({inverter.serial_number for inverter in self.inverters} - failed.keys(), failed)

    async def _async_read_inverters(self) -> tuple[list[InverterData], dict[str, ModbusError]]:
        known = self.inverters
        data: list[InverterData] = []
        failed: dict[str, ModbusError] = {}
        for i in range(self._MAX_INVERTER_COUNT):
            start_address = i * self._INVERTER_ADDRESS_STRIDE + self._INVERTER_BASE_ADDRESS
            try:
                registers = await _read_block(self._unit, start_address, self._INVERTER_REGISTER_COUNT)
            except ModbusConnectionError:
                raise
            except ModbusError as err:
                if i < len(known):
                    # The slot keeps the inverter the last update read, which also keeps
                    # the numbering of the slots behind it intact.
                    failed[known[i].serial_number] = err
                    data.append(known[i])
                    continue
                if not data:
                    raise  # the plant was never read, so there is nothing partial to report
                # No update has read this slot, so there is no inverter to keep in it and
                # no telling whether the plant ends here. The next update scans again.
                failed[f'slot {i}'] = err
                break
            data_to_unpack = _to_bytes(registers)[: self._INVERTER_DATA_SIZE]
            if i < 1 and len(data_to_unpack) < 1:
                raise InvertersNotMappedError("Inverters not mapped yet.")
            try:
                inverter_data = InverterData.unpack(data_to_unpack)
            except UnpackError as err:
                raise InverterDataError(
                    f'Could not decode inverter {i}: the DTU answered with '
                    f'{len(data_to_unpack)} of {self._INVERTER_DATA_SIZE} bytes'
                ) from err
            if inverter_data.serial_number == self._NULL_INVERTER:
                break
            data.append(inverter_data)
        return data, failed

    def _calculate_plant_data(self) -> PlantData:
        data = PlantData(self.dtu, inverters=self.inverters)
        for inverter in self.inverters:
            # calculate plant data from inverters
            # only active inverters are included
            if inverter.link_status:
                data.pv_power += inverter.pv_power
                data.today_production += inverter.today_production
                data.total_production += inverter.total_production
                if inverter.alarm_code:
                    data.alarm_flag = True
        return data
