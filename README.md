# hoymiles_modbus


[![pypi](https://img.shields.io/pypi/v/hoymiles_modbus.svg)](https://pypi.org/project/hoymiles_modbus/)
[![python](https://img.shields.io/pypi/pyversions/hoymiles_modbus.svg)](https://pypi.org/project/hoymiles_modbus/)
[![Build Status](https://github.com/wasilukm/hoymiles_modbus/actions/workflows/dev.yml/badge.svg)](https://github.com/wasilukm/hoymiles_modbus/actions/workflows/dev.yml)
[![codecov](https://codecov.io/gh/wasilukm/hoymiles_modbus/branch/main/graphs/badge.svg)](https://codecov.io/github/wasilukm/hoymiles_modbus)



Python library for gathering data from Hoymiles inverters.

The library communicates with Hoymiles DTU (Pro and Pro-S are supported) which is
a proxy/monitoring device for inverters.
DTU should be connected via its `Ethernet` port and should have IP address assigned by DHCP server.

Disclaimer: This is an independent project, not affiliated with Hoymiles. Any trademarks or product names mentioned are the property of their respective owners.


* Documentation: <https://wasilukm.github.io/hoymiles_modbus>
* GitHub: <https://github.com/wasilukm/hoymiles_modbus>
* PyPI: <https://pypi.org/project/hoymiles_modbus/>
* Free software: MIT


## Features

* Asynchronous communication, built on [modbus-connection](https://home-assistant-libs.github.io/modbus-connection/)
* Works over any transport that modbus-connection supports, with the caller owning the connection
* Tolerates DTUs that misreport the data size of their responses
* Keeps the plant readable when the DTU goes quiet on one inverter
* Decode all inverter status registers, which include information such as:
  * current production
  * total production
  * today production
  * temperature
  * alarms
  * status
  * grid voltage and frequency

## Partial updates

A plant is read one block per inverter, and those blocks are independent: one inverter the DTU
will not answer for does not take the rest of the plant with it. `async_update()` returns an
`UpdateReport` — an inverter whose block failed keeps the data of the update before and is listed
by serial number with the error that failed it, while every other inverter refreshes. Only a dead
link (`ModbusConnectionError`) raises:

```python
report = await device.async_update()
for serial_number, error in report.failed.items():
    print(f'{serial_number} kept the data of the previous update: {error}')
```

## Applications
This library is for creating higher-level applications such as [Home Assistant integration](https://github.com/wasilukm/hoymiles-mqtt)

## Credits

This package was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and the [waynerv/cookiecutter-pypackage](https://github.com/waynerv/cookiecutter-pypackage) project template.
