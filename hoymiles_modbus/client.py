"""Hoymiles Modbus client."""

from typing import TYPE_CHECKING, Optional

from ._quirks import apply_dtu_quirks
from .datatypes import InverterData, PlantData, _serial_number_t

if TYPE_CHECKING:  # pragma: no cover
    from modbus_connection import ModbusUnit


def _to_bytes(registers: list[int]) -> bytes:
    return b''.join(register.to_bytes(2, 'big') for register in registers)


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
        """Status data from all inverters, as of the last update."""
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
        registers = await unit.read_holding_registers(
            cls._DTU_SERIAL_NUMBER_ADDRESS, cls._DTU_SERIAL_NUMBER_REGISTER_COUNT
        )
        return _serial_number_t.unpack(_to_bytes(registers))

    async def async_update(self) -> None:
        """Refresh all data with a new request to the installation."""
        await apply_dtu_quirks(self._unit)
        self.inverters = await self._async_read_inverters()
        if not self.dtu:
            self.dtu = await self.async_probe(self._unit)
        self.plant_data = self._calculate_plant_data()

    async def _async_read_inverters(self) -> list[InverterData]:
        data: list[InverterData] = []
        for i in range(self._MAX_INVERTER_COUNT):
            start_address = i * self._INVERTER_ADDRESS_STRIDE + self._INVERTER_BASE_ADDRESS
            registers = await self._unit.read_holding_registers(start_address, self._INVERTER_REGISTER_COUNT)
            data_to_unpack = _to_bytes(registers)[: self._INVERTER_DATA_SIZE]
            if i < 1 and len(data_to_unpack) < 1:
                raise RuntimeError("Inverters not mapped yet.")
            inverter_data = InverterData.unpack(data_to_unpack)
            if inverter_data.serial_number == self._NULL_INVERTER:
                break
            data.append(inverter_data)
        return data

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
