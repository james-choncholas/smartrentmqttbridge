import os
import time
import ssl
import websockets
import paho.mqtt.client as mqtt

import asyncio
from smartrent import async_login

SMARTRENT_EMAIL = os.environ.get('SMARTRENT_EMAIL')
SMARTRENT_PASS = os.environ.get('SMARTRENT_PASS')

MQTT_HOST = os.environ.get('MQTT_HOST')
MQTT_PORT = int(os.environ.get('MQTT_PORT'))
MQTT_USER = os.environ.get('MQTT_USER')
MQTT_PASS = os.environ.get('MQTT_PASS')
MQTT_TLS = os.environ.get('MQTT_TLS') == "True"
MQTT_TOPIC_PREFIX = os.environ.get('MQTT_TOPIC_PREFIX')


TOPIC_LOCK = MQTT_TOPIC_PREFIX + '/lock'
TOPIC_THERM_MODE = MQTT_TOPIC_PREFIX + '/thermostat/mode'
TOPIC_THERM_FAN_MODE = MQTT_TOPIC_PREFIX + '/thermostat/fan'
TOPIC_THERM_SET_TEMP = MQTT_TOPIC_PREFIX + '/thermostat/setpoint'
TOPIC_THERM_CUR_TEMP = MQTT_TOPIC_PREFIX + '/thermostat/curtemp' #readonly
TOPIC_THERM_CUR_HUMI = MQTT_TOPIC_PREFIX + '/thermostat/curhumidity' #readonly

# https://www.home-assistant.io/docs/mqtt/discovery/
# single line string saves space in mqtt
LOCK_DISCOVERY = ('{'
  ' "name":"SmartRentLock0",'
  ' "state_topic":"' + TOPIC_LOCK + '/state",'
  ' "command_topic":"' + TOPIC_LOCK + '/set"'
'}')

# https://community.home-assistant.io/t/thermostats-climate-hvac/232340
THERMOSTAT_DISCOVERY = ('{'
  ' "name":"SmartRentThermostat0",'
  ' "mode_cmd_t":"' + TOPIC_THERM_MODE + '/set",'
  ' "mode_stat_t":"' + TOPIC_THERM_MODE + '/state",'
  ' "modes":["off", "heat", "cool", "auto"],'
  ' "fan_mode_command_topic":"' + TOPIC_THERM_FAN_MODE + '/set",'
  ' "fan_mode_state_topic":"' + TOPIC_THERM_FAN_MODE + '/state",'
  ' "fan_modes":["on", "auto"],'
  ' "temp_cmd_t":"' + TOPIC_THERM_SET_TEMP + '/set",'
  ' "temp_stat_t":"' + TOPIC_THERM_SET_TEMP + '/state",'
  ' "curr_temp_t":"' + TOPIC_THERM_CUR_TEMP + '",'
  ' "min_temp":"60",'
  ' "max_temp":"85",'
  ' "temp_step":"1",'
  ' "temp_unit":"F",'
  ' "precision":"1.0",'
  ' "target_humidity_state_topic":"' + TOPIC_THERM_CUR_HUMI + '/state"'
'}')


class SmartRentBridge:
    async def create():
        self = SmartRentBridge()
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set(MQTT_USER, password=MQTT_PASS)
        if MQTT_TLS is True:
            print("Using MQTT TLS")
            self.mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None)
            self.mqtt_client.tls_insecure_set(not MQTT_TLS)

        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message

        self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.mqtt_client.loop_start()
        self.mqtt_client.subscribe(TOPIC_LOCK + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_MODE + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_FAN_MODE + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_SET_TEMP + '/set')

        api = await async_login(SMARTRENT_EMAIL, SMARTRENT_PASS)
        print("logged in to smartrent")

        print(str(len(api.get_thermostats())) + " thermostats found")
        self.thermo = api.get_thermostats()[0]
        self.thermo.start_updater()
        self.thermo.set_update_callback(self.therm_on_evt)
        #print("current temp is " + self.thermo.get_current_temp())

        print(str(len(api.get_locks())) + " locks found")
        self.lock = api.get_locks()[0]
        self.lock.start_updater()
        self.lock.set_update_callback(self.lock_on_evt)

        #print("published test to mqtt")
        #self.mqtt_client.publish(MQTT_TOPIC_PREFIX + '/testdev/testcmd', "hi2")

        print("starting home assistant discovery")
        self.mqtt_client.publish("homeassistant/lock/srlock0/config", LOCK_DISCOVERY)
        self.mqtt_client.publish("homeassistant/climate/srclimate0/config", THERMOSTAT_DISCOVERY)
        return self

    def on_mqtt_connect(self, client, userdata, flags, rc):
        print("Connected to MQTT broker with result code " + str(rc))

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic.split('/')
        device = topic[1]
        command = topic[2]
        value = msg.payload.decode()
        print("MQTT message for device: " + device + " command: " + command + " value: " + value)

        if device == "lock":
            if command == "set":
                print("setting lock to " + value)
                asyncio.run(self.lock.async_set_locked(value != "UNLOCK"))
            self.lock_on_evt() # update state topic

        if device == "thermostat":
            if command == "mode":
                if value != "heat" and value != "cool" and value != "auto" and value != "off":
                    print("Bad input " + value + " passed to thermostat/mode. Should be heat, cool, auto, or off")
                else:
                    print("setting thermostat mode to " + value)
                    asyncio.run(self.thermo.async_set_mode(value))
            if command == "fan":
                if value != "auto" and value != "on":
                    print("Bad input " + value + " passed to thermostat/fan. Should be auto or on")
                else:
                    print("setting thermostat fan mode to " + value)
                    asyncio.run(self.thermo.async_set_fan_mode(value))
            if command == "setpoint":
                    if self.thermo.get_mode() == "heat":
                        print("setting thermostat heating setpoint to " + value)
                        asyncio.run(self.thermo.async_set_heating_setpoint(int(float(value))))
                    else:
                        print("setting thermostat cooling setpoint to " + value)
                        asyncio.run(self.thermo.async_set_cooling_setpoint(int(float(value))))
            self.therm_on_evt() # update state topic


    def therm_on_evt(self):
        print("thermostat event, publishing to mqtt")
        self.mqtt_client.publish(TOPIC_THERM_MODE + '/state', self.thermo.get_mode())
        self.mqtt_client.publish(TOPIC_THERM_FAN_MODE + '/state', self.thermo.get_fan_mode())
        if self.thermo.get_mode() == "heat":
            self.mqtt_client.publish(TOPIC_THERM_SET_TEMP + '/state', self.thermo.get_heating_setpoint())
        else:
            self.mqtt_client.publish(TOPIC_THERM_SET_TEMP + '/state', self.thermo.get_cooling_setpoint())
        self.mqtt_client.publish(TOPIC_THERM_CUR_TEMP + '/state', self.thermo.get_current_temp())
        self.mqtt_client.publish(TOPIC_THERM_CUR_HUMI + '/state', self.thermo.get_current_humidity())

    def lock_on_evt(self):
        print("lock event, publishing to mqtt. state: " + "LOCKED" if self.lock.get_locked() else "UNLOCKED")
        self.mqtt_client.publish(TOPIC_LOCK + '/state', "LOCKED" if self.lock.get_locked() else "UNLOCKED")


async def main():
    await SmartRentBridge.create()
    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            break
        except websockets.exceptions.InvalidStatusCode:
            print("websocket timeout")
            pass
        except:
            print("general exception")
            pass
