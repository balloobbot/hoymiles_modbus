"""The raw register dump a bug report is filed with.

It covers what a poll reads and what only setup reads, and it is worth having exactly
when the plant is misbehaving - so an inverter that will not answer is left out of it
rather than costing the dump everything else.
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
    map_inverters,
    to_registers,
)


@pytest.fixture
def dtu_unit(mock_modbus_unit):
    """Build a mock unit answering as a DTU with a serial number and two inverters mapped."""
    mock_modbus_unit.holding[DTU_SERIAL_NUMBER_ADDRESS] = to_registers(example_dtu_serial_number_raw_data)
    map_inverters(mock_modbus_unit, example_mi_series_raw_data, example_hm_series_raw_data)
    return mock_modbus_unit


def _block(raw: dict[int, int], address: int, count: int) -> list[int]:
    """Return the words the dump holds for a block, so it can be read as one."""
    return [raw[address + i] for i in range(count)]


async def test_the_dump_covers_the_serial_number_block_and_every_inverter(dtu_unit):
    """Verify that the dump carries the plant and the block only setup ever reads."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()

    raw = (await device.async_read_raw())['holding']

    assert _block(raw, DTU_SERIAL_NUMBER_ADDRESS, 3) == to_registers(example_dtu_serial_number_raw_data)
    assert _block(raw, INVERTER_BASE_ADDRESS, 20) == to_registers(example_mi_series_raw_data)[:20]
    assert (
        _block(raw, INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE, 20)
        == to_registers(example_hm_series_raw_data)[:20]
    )


async def test_an_inverter_that_will_not_answer_is_left_out(dtu_unit):
    """Verify that one silent inverter does not cost the dump the rest of the plant."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    dtu_unit.fail_read(INVERTER_BASE_ADDRESS, ModbusTimeoutError('slow inverter'))

    raw = (await device.async_read_raw())['holding']

    assert INVERTER_BASE_ADDRESS not in raw
    assert _block(raw, DTU_SERIAL_NUMBER_ADDRESS, 3) == to_registers(example_dtu_serial_number_raw_data)
    assert (
        _block(raw, INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE, 20)
        == to_registers(example_hm_series_raw_data)[:20]
    )


async def test_a_dead_link_raises_instead_of_dumping_what_it_has(dtu_unit):
    """Verify that a link that is down is not mistaken for a plant that would not answer."""
    device = HoymilesDTU(dtu_unit)
    await device.async_update()
    dtu_unit.fail_requests(ModbusConnectionError('link down'))

    with pytest.raises(ModbusConnectionError):
        await device.async_read_raw()


async def test_a_plant_no_update_read_still_dumps_its_first_block(dtu_unit):
    """Verify that a DTU whose answer could not be decoded is still worth dumping.

    That is the report the dump exists for, and there is no plant to walk in it: the
    serial number block and the first inverter block are what the answer came from.
    """
    raw = (await HoymilesDTU(dtu_unit).async_read_raw())['holding']

    assert _block(raw, DTU_SERIAL_NUMBER_ADDRESS, 3) == to_registers(example_dtu_serial_number_raw_data)
    assert _block(raw, INVERTER_BASE_ADDRESS, 20) == to_registers(example_mi_series_raw_data)[:20]
    assert INVERTER_BASE_ADDRESS + INVERTER_ADDRESS_STRIDE not in raw
