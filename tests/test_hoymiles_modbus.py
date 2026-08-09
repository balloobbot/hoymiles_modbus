#!/usr/bin/env python
"""Tests for `hoymiles_modbus` package."""

from decimal import Decimal

import pytest
from modbus_connection import (
    ExceptionCode,
    IllegalDataAddressError,
    ModbusExceptionError,
    ModbusUnit,
    ReadBlock,
    ServerDeviceFailureError,
)
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
from plum.exceptions import UnpackError

from hoymiles_modbus.client import HoymilesDTU
from hoymiles_modbus.datatypes import InverterData
from hoymiles_modbus.exceptions import HoymilesModbusError, InverterDataError, InvertersNotMappedError

DTU_SERIAL_NUMBER_ADDRESS = 0x2000
INVERTER_BASE_ADDRESS = 0x1000
INVERTER_ADDRESS_STRIDE = 40

example_mi_series_raw_data = (
    b'\x0c\x1032\x41cU\x01\x01^\x00\x02\tM\x13\x88\x00f\x02\xef\x00\x01$G\x00+\x00\x03\x00\x00\x00\x00\x01'
    b'\x07\x00\x00\x00\x00\x00\x00'
)

example_hm_series_raw_data = (
    b'\x0c\x1132\x41cU\x01\x01^\x00\x02\tM\x13\x88\x00f\x02\xef\x00\x01$G\x00+\x00\x03\x00\x00\x00\x00\x01'
    b'\x07\x00\x00\x00\x00\x00\x00'
)

null_inverter_raw_data = bytes(40)

example_dtu_serial_number_raw_data = b'\x11\xd3a`\x081'


def to_registers(data: bytes) -> list[int]:
    """Convert raw response bytes to the register words a Modbus read returns."""
    return [int.from_bytes(data[i : i + 2], 'big') for i in range(0, len(data), 2)]


def map_inverters(unit, *raw_data: bytes) -> None:
    """Place inverter data blocks at the addresses the DTU serves them from."""
    for i, data in enumerate((*raw_data, null_inverter_raw_data)):
        unit.holding[INVERTER_BASE_ADDRESS + i * INVERTER_ADDRESS_STRIDE] = to_registers(data)


@pytest.fixture
def dtu_unit(mock_modbus_unit):
    """Build a mock unit answering as a DTU with a serial number mapped."""
    mock_modbus_unit.holding[DTU_SERIAL_NUMBER_ADDRESS] = to_registers(example_dtu_serial_number_raw_data)
    return mock_modbus_unit


expected_mi_series_inverter = InverterData(  # type: ignore[call-overload]
    data_type=12,
    serial_number='103332416355',
    port_number=1,
    pv_voltage=Decimal('35'),
    pv_current=Decimal('0.2'),
    grid_voltage=Decimal('238.1'),
    grid_frequency=Decimal('50'),
    pv_power=Decimal('10.2'),
    today_production=751,
    total_production=74823,
    temperature=Decimal('4.3'),
    operating_status=3,
    alarm_code=0,
    alarm_count=0,
    link_status=1,
    reserved=[7, 0, 0, 0, 0, 0, 0],
)

expected_hm_series_inverter = InverterData(  # type: ignore[call-overload]
    data_type=12,
    serial_number='113332416355',
    port_number=1,
    pv_voltage=Decimal('35'),
    pv_current=Decimal('0.02'),
    grid_voltage=Decimal('238.1'),
    grid_frequency=Decimal('50'),
    pv_power=Decimal('10.2'),
    today_production=751,
    total_production=74823,
    temperature=Decimal('4.3'),
    operating_status=3,
    alarm_code=0,
    alarm_count=0,
    link_status=1,
    reserved=[7, 0, 0, 0, 0, 0, 0],
)


async def test_inverter_data_decode_mi_series(dtu_unit):
    """Test decoding MI series inverter data."""
    map_inverters(dtu_unit, example_mi_series_raw_data)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.inverters == [expected_mi_series_inverter]


async def test_inverter_data_decode_hm_series(dtu_unit):
    """Test decoding HM inverter data."""
    map_inverters(dtu_unit, example_hm_series_raw_data)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.inverters == [expected_hm_series_inverter]


async def test_stop_inverter_data_decode_on_empty_serial(dtu_unit):
    """Verify that inverters data gathering stops on receiving first empty serial number."""
    map_inverters(dtu_unit, example_mi_series_raw_data)
    # a block behind the null inverter is never reached
    dtu_unit.holding[INVERTER_BASE_ADDRESS + 2 * INVERTER_ADDRESS_STRIDE] = to_registers(example_hm_series_raw_data)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.inverters == [expected_mi_series_inverter]
    assert len(dtu_unit.read_events) == 3  # two inverter blocks, then the serial number


async def test_dtu(dtu_unit):
    """Test decoding DTU serial number."""
    map_inverters(dtu_unit)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.dtu == '11d361600831'


async def test_dtu_serial_number_read_once(dtu_unit):
    """Verify that the DTU serial number is read only on the first update."""
    map_inverters(dtu_unit)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    reads_after_first_update = len(dtu_unit.read_events)
    await device.async_update()
    assert len(dtu_unit.read_events) == reads_after_first_update + 1  # only the inverter scan repeats


async def test_probe(dtu_unit):
    """Verify that probing reads the serial number without polling inverters."""
    map_inverters(dtu_unit, example_mi_series_raw_data)
    assert await HoymilesDTU.async_probe(dtu_unit) == '11d361600831'
    assert [event.address for event in dtu_unit.read_events] == [DTU_SERIAL_NUMBER_ADDRESS]


async def test_plant_data(dtu_unit):
    """Test calculated values in plant data."""
    map_inverters(dtu_unit, example_mi_series_raw_data, example_hm_series_raw_data)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.plant_data.dtu == '11d361600831'
    assert device.plant_data.pv_power == Decimal('20.4')
    assert device.plant_data.today_production == 1502
    assert device.plant_data.total_production == 149646
    assert device.plant_data.inverters == [expected_mi_series_inverter, expected_hm_series_inverter]


async def test_no_alarm(dtu_unit):
    """Test inactive alarm in plant data."""
    map_inverters(dtu_unit, example_mi_series_raw_data)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.plant_data.alarm_flag is False


async def test_alarm(dtu_unit):
    """Test active alarm in plant data."""
    alarming_inverter = bytearray(example_mi_series_raw_data)
    alarming_inverter[29] = 1  # alarm code
    map_inverters(dtu_unit, bytes(alarming_inverter))
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert device.plant_data.alarm_flag is True


async def test_unlinked_inverter_excluded_from_plant_data(dtu_unit):
    """Verify that an inverter without link is not counted towards plant data."""
    unlinked_inverter = bytearray(example_mi_series_raw_data)
    unlinked_inverter[32] = 0  # link status
    map_inverters(dtu_unit, example_mi_series_raw_data, bytes(unlinked_inverter))
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert len(device.plant_data.inverters) == 2
    assert device.plant_data.today_production == 751  # only the linked one


async def test_modbus_error_propagates(dtu_unit):
    """Verify that a modbus error from a refused block is not swallowed."""
    dtu_unit.fail_read(INVERTER_BASE_ADDRESS, IllegalDataAddressError())
    with pytest.raises(IllegalDataAddressError) as err:
        await HoymilesDTU(dtu_unit).async_update()
    assert err.value.exception_code is ExceptionCode.ILLEGAL_DATA_ADDRESS


async def test_refused_inverter_block_says_which_one(dtu_unit):
    """Verify that a refusal names the inverter block it was about."""
    map_inverters(dtu_unit, example_mi_series_raw_data, example_hm_series_raw_data)
    second_inverter = INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE
    dtu_unit.fail_read(second_inverter, IllegalDataAddressError())

    with pytest.raises(IllegalDataAddressError) as err:
        await HoymilesDTU(dtu_unit).async_update()
    assert err.value.block == ReadBlock('holding', second_inverter, 20)


async def test_refused_serial_number_read_says_which_block(dtu_unit):
    """Verify that a refused probe names the serial number block."""
    dtu_unit.fail_read(DTU_SERIAL_NUMBER_ADDRESS, IllegalDataAddressError())
    with pytest.raises(IllegalDataAddressError) as err:
        await HoymilesDTU.async_probe(dtu_unit)
    assert err.value.block == ReadBlock('holding', DTU_SERIAL_NUMBER_ADDRESS, 3)


async def test_block_from_the_modelling_layer_is_kept(dtu_unit):
    """Verify that a block the connection already recorded is not overwritten."""
    already_blamed = ReadBlock('holding', 0x4321, 7)
    refusal = IllegalDataAddressError()
    refusal.block = already_blamed
    dtu_unit.fail_read(INVERTER_BASE_ADDRESS, refusal)

    with pytest.raises(IllegalDataAddressError) as err:
        await HoymilesDTU(dtu_unit).async_update()
    assert err.value.block is already_blamed


async def test_silent_dtu_error_propagates(dtu_unit):
    """Verify that a DTU which answers nothing at all surfaces as a modbus error."""
    dtu_unit.fail_requests(ServerDeviceFailureError())
    with pytest.raises(ModbusExceptionError):
        await HoymilesDTU(dtu_unit).async_update()
    assert dtu_unit.read_events  # the attempt was made before it raised


class _EmptyResponseUnit(MockModbusUnit):
    """A unit whose reads come back empty, as an unmapped DTU answers them.

    The DTU replies with no data at all, which the data size fixer turns into zero
    registers rather than a decoding error - see `hoymiles_modbus._quirks`.
    """

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        return []


async def test_exception_when_no_inverters():
    """Test exception when there are no inverters."""
    unit = _EmptyResponseUnit(MockModbusConnection(), 1)
    assert isinstance(unit, ModbusUnit)
    with pytest.raises(InvertersNotMappedError) as err:
        await HoymilesDTU(unit).async_update()
    assert str(err.value) == "Inverters not mapped yet."
    assert isinstance(err.value, RuntimeError)  # what the library raised before


class _ShortSecondBlockUnit(MockModbusUnit):
    """A DTU that answers a later inverter block with less data than it asked for."""

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        if address == INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE:
            return [0, 0]
        return await super().read_holding_registers(address, count)


async def test_short_inverter_block_is_a_library_error():
    """Verify that a truncated inverter block does not leak the decoder's own exception.

    The data size workaround makes such a response decodable as registers, but it cannot
    conjure the bytes the DTU never sent.
    """
    unit = _ShortSecondBlockUnit(MockModbusConnection(), 1)
    unit.holding[INVERTER_BASE_ADDRESS] = to_registers(example_mi_series_raw_data)

    with pytest.raises(InverterDataError) as err:
        await HoymilesDTU(unit).async_update()
    assert 'inverter 1' in str(err.value)
    assert '4 of 40 bytes' in str(err.value)
    assert isinstance(err.value.__cause__, UnpackError)


async def test_short_serial_number_read_is_a_library_error():
    """Verify that a truncated serial number response is reported as a library error."""
    unit = _EmptyResponseUnit(MockModbusConnection(), 1)
    with pytest.raises(InverterDataError):
        await HoymilesDTU.async_probe(unit)


def test_library_errors_share_a_base():
    """Verify that one except clause covers everything this library raises itself."""
    assert issubclass(InvertersNotMappedError, HoymilesModbusError)
    assert issubclass(InverterDataError, HoymilesModbusError)
    assert issubclass(HoymilesModbusError, RuntimeError)
