# Usage

The library reads a DTU through a [modbus-connection](https://home-assistant-libs.github.io/modbus-connection/)
`ModbusUnit`. The caller owns the connection, so one link can be shared and closed on the
caller's terms.

```python
import asyncio

from modbus_connection import ModbusTcpParams
from modbus_connection.pymodbus import ModbusConnection

from hoymiles_modbus.client import HoymilesDTU


async def main():
    connection = ModbusConnection(ModbusTcpParams(host='1.2.3.4'))
    try:
        device = HoymilesDTU(connection.for_unit(1))
        await device.async_update()
        print(device.plant_data.today_production)
    finally:
        await connection.close()


asyncio.run(main())
```

`async_update()` issues a new request to the installation and refreshes `dtu`,
`inverters` and `plant_data`. The DTU serial number is read only on the first update.

## Identifying a DTU during setup

To learn which DTU is at an address without polling the whole plant, probe it:

```python
serial_number = await HoymilesDTU.async_probe(connection.for_unit(1))
```

## Choosing a backend

Use `modbus_connection.pymodbus`. Some DTUs send responses whose data size byte
disagrees with the payload they actually deliver, and only the pymodbus backend can be
adjusted to accept them. A `ModbusUnit` from another backend is accepted but such a DTU
will fail to decode.

## Unreliable DTUs

Hoymiles DTUs are known to answer slowly right after the link opens, and to reach a
state where the socket stays open but no request is ever answered. Two connection
settings help, both owned by the caller:

```python
connection = ModbusConnection(
    ModbusTcpParams(host='1.2.3.4'),
    connect_delay=1.0,  # pause after the link opens, before the first request
    message_spacing=0.1,  # pause between requests; a plant is read one inverter at a time
)
```

When the DTU stops answering altogether, drop the link and let the next update build a
new one. Unlike `close()`, the connection stays usable and the `HoymilesDTU` holding the
unit does not need rebuilding:

```python
from modbus_connection import ModbusTimeoutError

try:
    await device.async_update()
except ModbusTimeoutError:
    await connection.disconnect()
```

## Errors

Communication failures raise the
[modbus-connection exceptions](https://home-assistant-libs.github.io/modbus-connection/connection/reference/#exceptions),
all of which derive from `ModbusError`. A device that refuses a request raises the
subclass matching the exception code it answered with, so there is no need to compare
against numbers:

```python
from modbus_connection import IllegalDataAddressError, ModbusError

try:
    await device.async_update()
except IllegalDataAddressError as err:
    print(f'the DTU refused the register block at {err.block.address}')
except ModbusError as err:
    print(f'update failed: {err}')
```

A plant is read one block per inverter, so the exception code alone would not say
which one the DTU refused. `err.block` is the `ReadBlock(space, address, count)` that
was refused, the same attribute the device modelling layer sets.

A DTU that responds but has not mapped its inverters yet raises `RuntimeError`.
