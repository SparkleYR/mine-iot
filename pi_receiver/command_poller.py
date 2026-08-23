#!/usr/bin/env python3
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Import local Hardware Actuator Driver
try:
    from actuator_controller import ActuatorController
except ImportError:
    try:
        from pi_receiver.actuator_controller import ActuatorController
    except ImportError:
        ActuatorController = None

LOG_FILE = os.path.expanduser("~/mine-iot/pi_receiver/command_poller.log")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[
    logging.FileHandler(LOG_FILE),
    logging.StreamHandler(sys.stdout)
])
logger = logging.getLogger("CommandPoller")

API_URL_NGROK = "https://commute-overrule-employer.ngrok-free.dev/api/v1/commands/pending"
API_URL_LOCAL = "http://192.168.1.1:4000/api/v1/commands/pending"
API_ACK_NGROK_TMPL = "https://commute-overrule-employer.ngrok-free.dev/api/v1/commands/{id}/ack"
API_ACK_LOCAL_TMPL = "http://192.168.1.1:4000/api/v1/commands/{id}/ack"

MQTT_HOST = "localhost"
MQTT_PORT = 1883
POLL_INTERVAL = 2.0
GATEWAY_ID = "pi4-gateway"
USER_AGENT = "MinePi4-CommandPoller/1.0"

HEADERS_GET = {
    "Accept": "application/json",
    "ngrok-skip-browser-warning": "1",
    "User-Agent": USER_AGENT
}

HEADERS_POST = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "1",
    "User-Agent": USER_AGENT
}


class CommandPollerDaemon:
    def __init__(self):
        self.running = False
        self.mqtt_client = mqtt.Client(client_id="CommandPollerDaemon")
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

        # Physical Actuator Controller (WS2812 on Pin 15, Buzzer on Pin 19)
        if ActuatorController:
            self.actuators = ActuatorController(ws2812_pin=15, buzzer_pin=19)
        else:
            self.actuators = None
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe("esp32/commands")
            client.subscribe("esp32/alarm")
            client.subscribe("mine/actuators")
            logger.info("Subscribed to MQTT actuator & alarm topics")
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")

    def on_mqtt_disconnect(self, client, userdata, rc):
        logger.warning("Disconnected from MQTT broker")

    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode('utf-8')
            data = json.loads(payload_str)
            logger.info(f"Received MQTT command [{msg.topic}]: {payload_str}")

            if "alarm" in msg.topic:
                action = data.get("action", "")
                if action == "RAISE" or data.get("severity") == "CRITICAL":
                    self.trigger_alarm(True)
                elif action == "CLEAR":
                    self.trigger_alarm(False)
            elif "commands" in msg.topic or "actuators" in msg.topic:
                self.process_command(data)
        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def trigger_alarm(self, active: bool):
        """Triggers or silences emergency alarm on physical hardware."""
        if not self.actuators:
            return
        if active:
            self.actuators.set_pattern("DANGER_FLASH")
            self.actuators.set_buzzer(True, duration_ms=10000)
        else:
            self.actuators.set_buzzer(False)
            self.actuators.set_pattern("NORMAL_CHECK")

    def fetch_pending_commands(self):
        urls_to_try = [API_URL_LOCAL, API_URL_NGROK]
        
        for url in urls_to_try:
            req = urllib.request.Request(url, headers=HEADERS_GET)
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        return url, data.get("data", [])
            except urllib.error.URLError as e:
                logger.debug(f"Failed to fetch from {url}: {e}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON response from {url}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error fetching from {url}: {e}")
        
        return None, []
        
    def ack_command(self, base_url, cmd_id):
        is_ngrok = "ngrok" in base_url
        ack_tmpl = API_ACK_NGROK_TMPL if is_ngrok else API_ACK_LOCAL_TMPL
        ack_url = ack_tmpl.format(id=cmd_id)
        
        payload = {
            "status": "ACKED",
            "ackedBy": GATEWAY_ID,
            "ackedAt": datetime.now(timezone.utc).isoformat()
        }
        data = json.dumps(payload).encode('utf-8')
        
        req = urllib.request.Request(ack_url, data=data, headers=HEADERS_POST, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status in (200, 201):
                    logger.info(f"Successfully acked command {cmd_id}")
                    return True
                else:
                    logger.error(f"Failed to ack command {cmd_id}, status: {response.status}")
        except Exception as e:
            logger.error(f"Error acking command {cmd_id} at {ack_url}: {e}")
        return False
        
    def process_command(self, cmd):
        cmd_id = cmd.get("id") or cmd.get("commandId")
        cmd_type = cmd.get("type")
        target = cmd.get("targetNodeId", "ALL")
        payload = cmd.get("payload", {})
        
        if not cmd_type:
            logger.error(f"Invalid command format: {cmd}")
            return
            
        logger.info(f"Processing command: {cmd_id} of type '{cmd_type}' for target '{target}'")
        
        # 1. Forward to ESP32 MQTT topic for wireless nodes
        mqtt_payload = {
            "commandId": cmd_id,
            "type": cmd_type,
            "targetNodeId": target,
            "payload": payload,
            "issuedAt": datetime.now(timezone.utc).isoformat()
        }
        self.mqtt_client.publish("esp32/commands", json.dumps(mqtt_payload))
        
        # 2. Directly trigger local Raspberry Pi 4 hardware actuators (Pin 15 & Pin 19)
        if self.actuators:
            if cmd_type in ("BUZZER_TEST", "BUZZER_ON"):
                active = payload.get("active", True)
                duration = payload.get("durationMs", 5000) if active else 0
                self.actuators.set_buzzer(active, duration_ms=duration)
            elif cmd_type == "BUZZER_OFF":
                self.actuators.set_buzzer(False)
            elif cmd_type in ("LED_TEST", "LED_PATTERN"):
                pattern = payload.get("pattern", "NORMAL_CHECK")
                self.actuators.set_pattern(pattern)
            elif cmd_type == "RAISE_ALARM":
                self.trigger_alarm(True)
                alarm_payload = {"action": "RAISE", "severity": "CRITICAL"}
                self.mqtt_client.publish("esp32/alarm", json.dumps(alarm_payload))
            elif cmd_type in ("CLEAR_ALARM", "RESOLVE_ALARM"):
                self.trigger_alarm(False)
                alarm_payload = {"action": "CLEAR"}
                self.mqtt_client.publish("esp32/alarm", json.dumps(alarm_payload))

    def run(self):
        self.running = True
        logger.info("Starting CommandPollerDaemon with Actuator Integration (Pin 15 WS2812 & Pin 19 Buzzer)")
        
        if self.actuators:
            self.actuators.start()

        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.warning(f"Could not connect to local MQTT at {MQTT_HOST}:{MQTT_PORT} ({e}). Running HTTP poller.")
        
        while self.running:
            start_time = time.time()
            try:
                successful_url, commands = self.fetch_pending_commands()
                if successful_url and commands:
                    logger.info(f"Fetched {len(commands)} pending command(s) from {successful_url}")
                    for cmd in commands:
                        self.process_command(cmd)
                        cmd_id = cmd.get("id") or cmd.get("commandId")
                        if cmd_id:
                            self.ack_command(successful_url, cmd_id)
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                
            elapsed = time.time() - start_time
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            if sleep_time > 0 and self.running:
                time.sleep(sleep_time)
                
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        if self.actuators:
            self.actuators.stop()
        logger.info("CommandPollerDaemon stopped")

    def stop(self):
        logger.info("Initiating shutdown...")
        self.running = False


def main():
    daemon = CommandPollerDaemon()
    
    def handle_sigint(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        daemon.stop()
        
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)
    
    daemon.run()


if __name__ == "__main__":
    main()

