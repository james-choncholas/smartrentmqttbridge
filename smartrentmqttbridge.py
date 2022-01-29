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
  ' "temp_unit":"F"'
'}')
  #' "precision":"1.0"'
  #' "target_humidity_state_topic":"' + TOPIC_THERM_CUR_HUMI + '/state"'


class SmartRentBridge:
    async def create():
        self = SmartRentBridge()
        await self.setupMqtt()
        await self.setupSmartRent()
        return self

    async def setupMqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set(MQTT_USER, password=MQTT_PASS)
        if MQTT_TLS is True:
            print("Using MQTT TLS")
            self.mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None)
            self.mqtt_client.tls_insecure_set(not MQTT_TLS)

        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.mqttHandleMessage

        self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.mqtt_client.loop_start()
        self.mqtt_client.subscribe(TOPIC_LOCK + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_MODE + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_FAN_MODE + '/set')
        self.mqtt_client.subscribe(TOPIC_THERM_SET_TEMP + '/set')

        print("starting home assistant discovery")
        self.mqtt_client.publish("homeassistant/lock/srlock0/config", LOCK_DISCOVERY, retain=True)
        self.mqtt_client.publish("homeassistant/climate/srclimate0/config", THERMOSTAT_DISCOVERY, retain=True)


    async def setupSmartRent(self):
        self.api = await async_login(SMARTRENT_EMAIL, SMARTRENT_PASS)
        print("logged in to smartrent")

        print(str(len(self.api.get_thermostats())) + " thermostats found")
        self.thermo = self.api.get_thermostats()[0]
        self.thermo.start_updater()
        self.thermo.set_update_callback(self.srThermEvent)
        #print("current temp is " + self.thermo.get_current_temp())

        print(str(len(self.api.get_locks())) + " locks found")
        self.lock = self.api.get_locks()[0]
        self.lock.start_updater()
        self.lock.set_update_callback(self.srLockEvent)

    def on_mqtt_connect(self, client, userdata, flags, rc):
        print("Connected to MQTT broker with result code " + str(rc))

    def mqttHandleMessage(self, client, userdata, msg):
        topic = msg.topic.split('/')
        device = topic[1]
        command = topic[2]
        value = msg.payload.decode()
        print("MQTT message for device: " + device + " command: " + command + " value: " + value)
        for x in range(3):
            try:
                asyncio.run(self.handleMessage(device, command, value))
                break;
            except RuntimeError:
                # smartrent.py raises websockets.exceptions.InvalidStatusCode
                # with error 403, causes mqtt to throw RuntimeError
                print("Runtime error. Renewing smartrent api")
                asyncio.run(self.setupSmartRent())
        else:
            raise Exception("smartrent failed to connect 3 times in a row")

    async def handleMessage(self, device, command, value):
        if device == "lock":
            if command == "set":
                print("setting lock to " + value)
                await self.lock.async_set_locked(value != "UNLOCK")
            self.srLockEvent() # update state topic

        if device == "thermostat":
            if command == "mode":
                if value != "heat" and value != "cool" and value != "auto" and value != "off":
                    print("Bad input " + value + " passed to thermostat/mode. Should be heat, cool, auto, or off")
                else:
                    print("setting thermostat mode to " + value)
                    await self.thermo.async_set_mode(value)
            if command == "fan":
                if value != "auto" and value != "on":
                    print("Bad input " + value + " passed to thermostat/fan. Should be auto or on")
                else:
                    print("setting thermostat fan mode to " + value)
                    await self.thermo.async_set_fan_mode(value)
            if command == "setpoint":
                    if self.thermo.get_mode() == "heat":
                        print("setting thermostat heating setpoint to " + value)
                        await self.thermo.async_set_heating_setpoint(int(float(value)))
                    else:
                        print("setting thermostat cooling setpoint to " + value)
                        await self.thermo.async_set_cooling_setpoint(int(float(value)))
            self.srThermEvent() # update state topic


    def srThermEvent(self):
        print("thermostat event, publishing to mqtt")
        self.mqtt_client.publish(TOPIC_THERM_MODE + '/state', self.thermo.get_mode())
        self.mqtt_client.publish(TOPIC_THERM_FAN_MODE + '/state', self.thermo.get_fan_mode())
        if self.thermo.get_mode() == "heat":
            self.mqtt_client.publish(TOPIC_THERM_SET_TEMP + '/state', self.thermo.get_heating_setpoint())
        else:
            self.mqtt_client.publish(TOPIC_THERM_SET_TEMP + '/state', self.thermo.get_cooling_setpoint())
        self.mqtt_client.publish(TOPIC_THERM_CUR_TEMP + '/state', self.thermo.get_current_temp())
        self.mqtt_client.publish(TOPIC_THERM_CUR_HUMI + '/state', self.thermo.get_current_humidity())

    def srLockEvent(self):
        print("lock event, publishing to mqtt. state: " + "LOCKED" if self.lock.get_locked() else "UNLOCKED")
        self.mqtt_client.publish(TOPIC_LOCK + '/state', "LOCKED" if self.lock.get_locked() else "UNLOCKED")


async def main():
    while True:
        #loop.create_task(SmartRentBridge.create(), loop=loop)
        sr = await SmartRentBridge.create()

        #loop = asyncio.get_event_loop()
        #def eh(loop, context):
        #    # context["message"] will always be there; but context["exception"] may not
        #    msg = context.get("exception", context["message"])
        #    print("Caught exception: "+msg)

        #loop.set_exception_handler(eh)

        while True:
            await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
