import time

import bidict
import paho.mqtt.client

import controller
import usb.core
import paho.mqtt as mqtt
import json


class MqttBridge:
    def __init__(self):
        self.charger_controllers = None
        self.mqtt = paho.mqtt.client.Client('charger')
        self.mqtt.on_message = self.on_message
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_disconnect = self.on_disconnect

    def on_disconnect(self, arg1, arg2, arg4):
        print('mqtt disconnected')

    def on_connect(self, arg1, arg2, arg3, arg4):
        print('mqtt connected')
        self.mqtt.subscribe('chargers/+/channels/+')

    def publish(self, topic: str, payload: str):
        self.mqtt.publish(topic, payload, retain=True)

    def main(self):
        controllers = []
        usb_devices = usb.core.find(find_all=True, idVendor=0, idProduct=1)
        for usb_device in usb_devices:
            controllers.append(
                {
                    'controller': controller.ChargerController(usb_device),
                    'last_channel_data': {}
                }
            )
        if len(controllers) == 0:
            raise RuntimeError('no chargers found')
        self.charger_controllers = controllers
        while True:
            try:
                self.mqtt.connect('home')
                break
            except ConnectionRefusedError:
                print('mqtt connect failed, retrying...')
                time.sleep(5)

        self.mqtt.loop_start()
        self.run_loop()

    def on_message(self, mqtt_object, status, message):
        topic = message.topic
        parts = topic.split('/')
        charger_num = int(parts[1])
        channel_num = int(parts[3])
        try:
            data = json.loads(message.payload)
            command = data['command']

            if command == 'stop':
                self.charger_controllers[charger_num]['controller'].stop_charge(channel_num)
                return

            cell_count = data['cell_count']
            current_ma = data['current_ma']

            if command == 'charge':
                self.charger_controllers[charger_num]['controller'].start_charge_lipo(channel_num, cell_count, current_ma)
            if command == 'storage':
                self.charger_controllers[charger_num]['controller'].start_storage_lipo(channel_num, cell_count, current_ma)
        except json.JSONDecodeError as e:
            print('error decoding command')
        except KeyError as e:
            print('missing command params')
            print(e)

    def run_loop(self):
        while True:
            time.sleep(5)
            for charger_num in range(len(self.charger_controllers)):
                controller_data = self.charger_controllers[charger_num]
                time.sleep(0.1)
                try:
                    charger_controller = controller_data.get('controller')
                    last_channel_data = controller_data.get('last_channel_data')
                    for channel_num in range(4):
                        time.sleep(0.2)
                        last_data = last_channel_data.get(channel_num, {})
                        current_data = charger_controller.get_channel_info(channel_num)

                        if controller_data.get('state', None) != 'connected':
                            print(f'controller #{charger_num} regained connection')
                            self.charger_controllers[charger_num]['state'] = 'connected'
                            self.publish(f'chargers/{charger_num}/state', 'connected')

                        for key in dict.keys(current_data):
                            current_value = current_data.get(key)
                            if isinstance(current_value, list):
                                continue
                            last_value = last_data.get(key)

                            if current_value != last_value:
                                last_data[key] = current_value
                                topic = f'chargers/{charger_num}/channels/{channel_num}/{key}'
                                print(f'publishing {topic}')
                                self.publish(topic, current_value)

                        last_cells = last_data.get('cells', [-1] * 6)
                        current_cells = current_data['cells']
                        for cell_num in range(0, len(current_data['cells'])):
                            if current_cells[cell_num] != last_cells[cell_num]:
                                last_cells[cell_num] = current_cells[cell_num]
                                topic = f'chargers/{charger_num}/channels/{channel_num}/cells/{cell_num}'
                                print(f'publishing {topic}')
                                self.publish(topic, current_cells[cell_num])
                        last_data['cells'] = last_cells

                        last_channel_data[channel_num] = last_data
                except controller.DeviceNotConnectedError:
                    if controller_data.get('state', None) != 'no_connection':
                        print(f'charger #{charger_num} lost connection')
                        self.charger_controllers[charger_num]['state'] = 'no_connection'
                        self.publish(f'chargers/{charger_num}/state', 'no_connection')
                except usb.USBError:
                    if controller_data.get('state', None) != 'communication_error':
                        print(f'charger #{charger_num} communication error')
                        self.charger_controllers[charger_num]['state'] = 'communication_error'
                        self.publish(f'chargers/{charger_num}/state', 'communication_error')


if __name__ in ['mqtt.__main__', '__main__']:
    bridge = MqttBridge()
    bridge.main()
