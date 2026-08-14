"""One failing inverter block must not take the rest of the plant with it.

A plant is read one block per inverter, and a DTU that goes quiet on one of them is
ordinary: the blocks are independent, so the inverter that failed keeps the data of the
update before while the rest still refresh.
"""

import pytest
from modbus_connection import ModbusConnectionError, ModbusTimeoutError

from hoymiles_modbus import HoymilesDTU

from .test_hoymiles_modbus import (
    DTU_SERIAL_NUMBER_ADDRESS,
    INVERTER_ADDRESS_STRIDE,
    INVERTER_BASE_ADDRESS,
    example_dtu_serial_number_raw_data,
    example_hm_series_raw_data,
    example_mi_series_raw_data,
    expected_hm_series_inverter,
    expected_mi_series_inverter,
    map_inverters,
    to_registers,
)

MI_SERIAL = expected_mi_series_inverter.serial_number
HM_SERIAL = expected_hm_series_inverter.serial_number


def _with_today_production(raw_data: bytes, value: int) -> bytes:
    """Return an inverter block reporting a different today production."""
    data = bytearray(raw_data)
    data[18:20] = value.to_bytes(2, 'big')  # today_production, 18 bytes into the block
    return bytes(data)


def _with_serial_number(raw_data: bytes, serial_number: str) -> bytes:
    """Return an inverter block reporting a different serial number."""
    data = bytearray(raw_data)
    data[1:7] = bytes.fromhex(serial_number)
    return bytes(data)


@pytest.fixture
def dtu_unit(mock_modbus_unit):
    """Build a mock unit answering as a DTU with a serial number and two inverters mapped."""
    mock_modbus_unit.holding[DTU_SERIAL_NUMBER_ADDRESS] = to_registers(example_dtu_serial_number_raw_data)
    map_inverters(mock_modbus_unit, example_mi_series_raw_data, example_hm_series_raw_data)
    return mock_modbus_unit


async def test_a_failed_inverter_leaves_the_rest_fresh(dtu_unit):
    """Verify that one silent inverter block does not cost the plant its other inverters."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    # Both inverters produce more than they did, but the DTU stops answering for the second.
    map_inverters(
        dtu_unit,
        _with_today_production(example_mi_series_raw_data, 800),
        _with_today_production(example_hm_series_raw_data, 900),
    )
    dtu_unit.fail_read(INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE, ModbusTimeoutError('slow inverter'))
    report = await device.async_update()

    assert not report.complete
    assert set(report.failed) == {HM_SERIAL}
    assert isinstance(report.failed[HM_SERIAL], ModbusTimeoutError)
    assert report.updated == {MI_SERIAL}
    assert device.inverters[0].today_production == 800
    assert device.inverters[1].today_production == 751  # the previous value, kept


async def test_a_silent_plant_raises_instead_of_a_timeout_per_inverter(dtu_unit):
    """Verify that a DTU which answers nothing at all is not walked inverter by inverter.

    The blocks are independent, but a first block that times out means the DTU is silent
    rather than slow - reading on would only pay the timeout again for every inverter.
    """
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    dtu_unit.fail_requests(ModbusTimeoutError('silent DTU'))
    with pytest.raises(ModbusTimeoutError):
        await device.async_update()
    assert device.inverters == [expected_mi_series_inverter, expected_hm_series_inverter]


async def test_a_failed_inverter_still_counts_towards_the_plant(dtu_unit):
    """Verify that plant totals keep including an inverter whose block failed."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    dtu_unit.fail_read(INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE, ModbusTimeoutError('slow inverter'))
    await device.async_update()

    assert device.plant_data.dtu == '11d361600831'
    assert device.plant_data.today_production == 1502  # both inverters, one of them stale
    assert len(device.plant_data.inverters) == 2


async def test_a_failure_in_the_middle_keeps_the_slots_in_order(dtu_unit):
    """Verify that a failed block holds its place, so later inverters stay where they are."""
    third_inverter = _with_serial_number(example_mi_series_raw_data, '103332416399')
    map_inverters(dtu_unit, example_mi_series_raw_data, example_hm_series_raw_data, third_inverter)
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    dtu_unit.fail_read(INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE, ModbusTimeoutError('slow inverter'))
    report = await device.async_update()

    assert set(report.failed) == {HM_SERIAL}
    assert [inverter.serial_number for inverter in device.inverters] == [MI_SERIAL, HM_SERIAL, '103332416399']


async def test_a_slot_the_plant_never_had_is_reported_not_raised(dtu_unit):
    """Verify that a failure past the known plant is reported, leaving the inverters fresh.

    The block behind the last inverter is what ends the scan, and no update has read an
    inverter from it - so there is no serial number to name it by, and nothing to keep in
    it either.
    """
    device = HoymilesDTU(dtu_unit)
    terminator = INVERTER_BASE_ADDRESS + 2 * INVERTER_ADDRESS_STRIDE
    dtu_unit.fail_read(terminator, ModbusTimeoutError('slow DTU'))
    report = await device.async_update()

    assert set(report.failed) == {'slot 2'}
    assert report.updated == {MI_SERIAL, HM_SERIAL}
    assert device.inverters == [expected_mi_series_inverter, expected_hm_series_inverter]


async def test_every_inverter_refreshes_on_a_healthy_plant(dtu_unit):
    """Verify that an update nothing went wrong in reports itself as complete."""
    report = await HoymilesDTU(dtu_unit).async_update()

    assert report.complete
    assert report.failed == {}
    assert report.updated == {MI_SERIAL, HM_SERIAL}


async def test_the_first_inverter_block_of_the_first_update_still_raises(dtu_unit):
    """Verify that an update which read no inverter at all raises instead of reporting.

    Without a single inverter there is no plant to report against, and an empty plant is
    not what the DTU said.
    """
    device = HoymilesDTU(dtu_unit)
    dtu_unit.fail_read(INVERTER_BASE_ADDRESS, ModbusTimeoutError('slow inverter'))
    with pytest.raises(ModbusTimeoutError):
        await device.async_update()
    assert device.inverters == []

    dtu_unit.fail_read(INVERTER_BASE_ADDRESS, None)
    assert (await device.async_update()).complete


async def test_a_failed_serial_number_read_is_retried(dtu_unit):
    """Verify that a DTU which would not say who it is on one update is asked again."""
    device = HoymilesDTU(dtu_unit)
    dtu_unit.fail_read(DTU_SERIAL_NUMBER_ADDRESS, ModbusTimeoutError('slow DTU'))
    with pytest.raises(ModbusTimeoutError):
        await device.async_update()
    assert device.dtu == ''

    dtu_unit.fail_read(DTU_SERIAL_NUMBER_ADDRESS, None)
    assert (await device.async_update()).complete
    assert device.dtu == '11d361600831'


async def test_a_dead_link_raises_instead_of_reporting(dtu_unit):
    """Verify that a link that is down is not mistaken for inverters that failed."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    dtu_unit.fail_requests(ModbusConnectionError('link down'))
    with pytest.raises(ModbusConnectionError):
        await device.async_update()


async def test_an_inverter_added_later_is_still_discovered(dtu_unit):
    """Verify that containment did not settle the plant: every update scans it again."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    assert len(device.inverters) == 2

    third_inverter = _with_serial_number(example_mi_series_raw_data, '103332416399')
    map_inverters(dtu_unit, example_mi_series_raw_data, example_hm_series_raw_data, third_inverter)
    report = await device.async_update()

    assert report.updated == {MI_SERIAL, HM_SERIAL, '103332416399'}
