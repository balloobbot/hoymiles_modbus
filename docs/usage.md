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

## Errors

Communication failures raise the
[modbus-connection exceptions](https://home-assistant-libs.github.io/modbus-connection/connection/reference/#exceptions),
all of which derive from `ModbusError`:

```python
from modbus_connection import ModbusError

try:
    await device.async_update()
except ModbusError as err:
    print(f'update failed: {err}')
```

A DTU that responds but has not mapped its inverters yet raises `RuntimeError`.
