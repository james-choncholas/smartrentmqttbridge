# SmartRent for Home Assistant
This connects to SmartRents API using the [smartrent.py](https://github.com/zacherythomas/smartrent.py) package from Zachery Thomas.
Then, it sets up thermostat and lock autodiscovery for home assistant via MQTT.

This package is similar to the [SmartRent-MQTT-Bridge](https://github.com/AMcPherran/SmartRent-MQTT-Bridge) project but is slightly simpler as it doesn't rely on the chrome hack.

This project only supports a single lock and thermostat (the configuration in my apartment.) If SmartRent gave you more than one, the first discovered will be used.

# Run
- Install Docker
- Build the container: `./build.sh`
- Set up environment variables in `smartrent.env`
- `./run.sh`
