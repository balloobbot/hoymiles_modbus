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
`inverters` and `plant_data`. The DTU serial number is read first, and only on the first
update - it identifies the installation, so until it is known there is nothing to report
against.

## Partial updates

A plant is read one block per inverter, and those blocks are independent: an inverter the
DTU will not answer for keeps the data of the update before while the rest still refresh.
The `UpdateReport` says which is which:

```python
report = await device.async_update()
if not report.complete:
    for serial_number, error in report.failed.items():
        print(f'{serial_number} kept the data of the previous update: {error}')
```

`failed` is keyed by inverter serial number. The block that ends the scan is the
exception: it is the one behind the last inverter, so no update has ever read an inverter
from it, and it appears as `slot <position>` instead. Nothing is stale when that block
fails - an inverter added to the DTU since the last update just stays undiscovered until
the next one.

A timeout is only contained once the DTU has answered something. When the very first block
times out the update raises `ModbusTimeoutError`: the DTU is silent rather than slow, and
walking the plant would pay the timeout again for every inverter in it.

## Identifying a DTU during setup

To learn which DTU is at an address without polling the whole plant, probe it:

```python
serial_number = await HoymilesDTU.async_probe(connection.for_unit(1))
```

## Diagnostics

`async_read_raw()` returns every register the library reads, undecoded, keyed by address
space and absolute address - what to attach to a bug report:

```python
raw = await device.async_read_raw()
print(raw['holding'][0x1000])
```

The serial number block is in there along with the plant, so the registers only setup
reads are not left out. The plant is dumped as the last update found it, plus the first
inverter block whether or not an update ever got that far - a DTU whose answer the library
could not decode is the report this exists for, and that block is the evidence.

An inverter that will not answer is left out of the dump rather than costing it the rest
of the plant, since a plant that is misbehaving is when the dump is worth having. A dead
link still raises `ModbusConnectionError`.

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
new one. Every inverter block failing is what that looks like from here, so the report is
what to watch. Unlike `close()`, the connection stays usable and the `HoymilesDTU` holding
the unit does not need rebuilding:

```python
report = await device.async_update()
if not report.updated:
    await connection.disconnect()
```

## Errors

Communication failures raise the
[modbus-connection exceptions](https://home-assistant-libs.github.io/modbus-connection/connection/reference/#exceptions),
all of which derive from `ModbusError`. A device that refuses a request raises the
subclass matching the exception code it answered with, so there is no need to compare
against numbers.

Most of them reach the caller through `report.failed` rather than by being raised. What
still raises is a dead link, the DTU serial number read, and an update that could not
read a single inverter - none of which leaves anything partial to report:

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
was refused, the same attribute the device modelling layer sets, and it is there whether
the error was raised or reported.

A DTU that answers with something the library cannot make sense of raises a
`HoymilesModbusError` instead. There are two, and both derive from `RuntimeError`, which
is what the library raised before they existed:

```python
from hoymiles_modbus import HoymilesModbusError, InverterDataError, InvertersNotMappedError

try:
    await device.async_update()
except InvertersNotMappedError:
    print('add the inverters to the DTU first')
except InverterDataError as err:
    print(f'the DTU sent an incomplete answer: {err}')
```

`InverterDataError` covers a DTU that sends fewer bytes than its own data size byte
claims. The data size workaround makes such a response decodable as Modbus registers; it
cannot supply the bytes that never arrived.

So a caller that wants everything needs two `except` clauses - `ModbusError` for the
link and the device's refusals, `HoymilesModbusError` for the DTU's own answers.
