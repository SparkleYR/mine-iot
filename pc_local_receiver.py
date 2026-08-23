#!/usr/bin/env python3
"""
PC Local Receiver & Intelligent Edge Command Gateway
===================================================
Lightweight HTTP server running on the user's Edge Laptop (192.168.1.1:4000) to:
  1. Ingest telemetry from Raspberry Pi 4 (Ethernet) -> local SQLite database.
  2. Maintain a local Outbound Command Queue for physical actuators (WS2812 & Buzzer).
  3. Bidirectionally sync with Cloud Backend:
       * Cloud Poller fetches pending commands from Cloud -> local queue for Pi 4
       * Forwards Pi 4 ACKs back to Cloud Backend
       * Accepts direct local REST commands (/api/v1/commands, /api/v1/alarms/manual)
"""

import os
import json
import uuid
import sqlite3
import logging
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("PCLocalReceiver")

# Constants
HOST = '0.0.0.0'
PORT = 4000
DB_PATH = os.path.expanduser('~/mine-iot/pc_telemetry.db')
CLOUD_BASE = "https://35-154-233-23.sslip.io"

# In-Memory Command Queue
command_lock = threading.Lock()
pending_commands = []
acked_command_ids = set()

def init_db():
    """Initialize the SQLite database and create tables if they do not exist."""
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir) and db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            seq INTEGER,
            device_ms INTEGER,
            vibration INTEGER,
            adxl_ax REAL,
            adxl_ay REAL,
            adxl_az REAL,
            mpu_ax REAL,
            mpu_ay REAL,
            mpu_az REAL,
            mpu_gx REAL,
            mpu_gy REAL,
            mpu_gz REAL,
            distance_cm REAL,
            buzzer INTEGER,
            mq2_raw INTEGER,
            temperature REAL,
            humidity REAL,
            received_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS edge_commands (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            payload TEXT,
            issued_by TEXT,
            issued_at TEXT,
            status TEXT DEFAULT 'PENDING'
        )
    ''')

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def insert_reading(node_id, payload, received_at):
    """Insert a single reading into the SQLite database."""
    if not isinstance(payload, dict):
        return
    if 'commandId' in payload or 'action' in payload or 'issuedBy' in payload:
        return
    if 'adxl345' not in payload and 'mpu6050' not in payload and 'gy87_mpu' not in payload and 'seq' not in payload:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    seq = payload.get('seq')
    ms = payload.get('ms')
    vib = payload.get('vib')
    
    adxl = payload.get('adxl345') or payload.get('gy87_mpu') or {}
    adxl_ax = adxl.get('ax')
    adxl_ay = adxl.get('ay')
    adxl_az = adxl.get('az')
    
    mpu = payload.get('mpu6050') or {}
    mpu_ax = mpu.get('ax')
    mpu_ay = mpu.get('ay')
    mpu_az = mpu.get('az')
    mpu_gx = mpu.get('gx')
    mpu_gy = mpu.get('gy')
    mpu_gz = mpu.get('gz')
    
    distance = payload.get('distance_cm')
    buzzer = payload.get('buzzer')
    mq2 = payload.get('mq2_raw')
    temp = payload.get('temperature')
    hum = payload.get('humidity')
    
    cursor.execute('''
        INSERT INTO sensor_readings (
            device_id, seq, device_ms, vibration, 
            adxl_ax, adxl_ay, adxl_az, 
            mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz, 
            distance_cm, buzzer, mq2_raw, temperature, humidity, 
            received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        node_id, seq, ms, vib,
        adxl_ax, adxl_ay, adxl_az,
        mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz,
        distance, buzzer, mq2, temp, hum,
        received_at
    ))
    
    conn.commit()
    conn.close()

def enqueue_local_command(cmd_type: str, target_node: str = "ALL", payload: dict = None, issued_by: str = "EDGE_LAPTOP") -> dict:
    """Enqueues a command locally for delivery to the Pi 4."""
    cmd_id = f"CMD-{int(time.time() * 1000)}-{str(uuid.uuid4())[:6]}"
    cmd = {
        "id": cmd_id,
        "type": cmd_type,
        "targetNodeId": target_node,
        "payload": payload or {},
        "issuedBy": issued_by,
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING"
    }
    with command_lock:
        pending_commands.append(cmd)
        if len(pending_commands) > 500:
            pending_commands.pop(0)

    logger.info(f"[EDGE QUEUE] Enqueued command: {cmd_id} ({cmd_type}) for {target_node}")
    return cmd

def forward_ack_to_cloud(cmd_id: str):
    """Worker to relay Pi 4 ACK back to Cloud Backend."""
    def _task():
        url = f"{CLOUD_BASE}/api/v1/commands/{cmd_id}/ack"
        data = json.dumps({"status": "ACKED", "ackedBy": "pi4-gateway"}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "1"
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=4) as res:
                if res.status in (200, 201):
                    logger.info(f"[CLOUD RELAY] Forwarded ACK for {cmd_id} to Cloud Backend.")
        except Exception as e:
            logger.debug(f"Could not forward ACK for {cmd_id} to cloud: {e}")

    threading.Thread(target=_task, daemon=True).start()

def sync_cloud_commands_loop():
    """Background worker that continuously pulls pending commands from Cloud Backend."""
    headers = {
        "Accept": "application/json",
        "ngrok-skip-browser-warning": "1",
        "User-Agent": "EdgeLaptop-Relay/1.0"
    }
    while True:
        try:
            url = f"{CLOUD_BASE}/api/v1/commands/pending"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as res:
                if res.status == 200:
                    data = json.loads(res.read().decode('utf-8'))
                    cloud_cmds = data.get("data", [])
                    with command_lock:
                        existing_ids = {c["id"] for c in pending_commands}.union(acked_command_ids)
                        for c in cloud_cmds:
                            if c.get("id") and c["id"] not in existing_ids:
                                pending_commands.append(c)
                                logger.info(f"[CLOUD SYNC] Ingested remote command from Cloud: {c.get('id')} ({c.get('type')})")
        except Exception as e:
            logger.debug(f"Cloud command sync check: {e}")
        time.sleep(2.0)

class RequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, ngrok-skip-browser-warning')
    
    def _send_response(self, status_code, payload):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))
        
    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            self._send_response(200, {"ok": True, "service": "pc-local-receiver", "gateway": "edge-laptop"})
        
        elif self.path.startswith('/api/v1/commands/pending'):
            with command_lock:
                active = [c for c in pending_commands if c.get("status") == "PENDING"]
            self._send_response(200, {"ok": True, "count": len(active), "data": active})
            
        elif self.path.startswith('/photos/'):
            filename = os.path.basename(self.path)
            img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_receiver", "captured_images")
            filepath = os.path.join(img_dir, filename)

            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self._send_cors_headers()
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self._send_response(404, {"ok": False, "error": "Image file not found"})

        else:
            self._send_response(404, {"ok": False, "error": "Not Found"})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            body = json.loads(post_data.decode('utf-8')) if post_data else {}
        except json.JSONDecodeError:
            self._send_response(400, {"ok": False, "error": "Invalid JSON"})
            return

        # 1. Telemetry Ingestion from Pi 4
        if self.path == '/api/v1/telemetry/ingest':
            results = []
            readings = body.get('readings', [])
            
            for reading in readings:
                node_id = reading.get('nodeId')
                payload = reading.get('payload', {})
                received_at = reading.get('receivedAt', datetime.now(timezone.utc).isoformat())
                
                try:
                    insert_reading(node_id, payload, received_at)
                    results.append({"nodeId": node_id, "status": "OK"})
                except Exception as e:
                    logger.error(f"Error inserting reading for {node_id}: {e}")
                    results.append({"nodeId": node_id, "status": "ERROR"})
                    
            logger.info(f"Ingested {len(results)} readings from Pi 4")
            self._send_response(200, {"ok": True, "results": results})

        # 2. Command Creation (Remote / Dashboard / Webhook)
        elif self.path == '/api/v1/commands':
            cmd_type = body.get("type", "BUZZER_TEST")
            target = body.get("targetNodeId", "ALL")
            payload = body.get("payload", {})
            issued_by = body.get("issuedBy", "DASHBOARD_OPERATOR")
            
            cmd = enqueue_local_command(cmd_type, target, payload, issued_by)
            self._send_response(201, {"ok": True, "data": cmd})

        # 3. Command Acknowledgment from Pi 4
        elif '/api/v1/commands/' in self.path and self.path.endswith('/ack'):
            parts = self.path.strip('/').split('/')
            cmd_id = parts[3]
            with command_lock:
                for c in pending_commands:
                    if c.get("id") == cmd_id:
                        c["status"] = "ACKED"
                        c["deliveredAt"] = datetime.now(timezone.utc).isoformat()
                        break
                acked_command_ids.add(cmd_id)

            forward_ack_to_cloud(cmd_id)
            logger.info(f"[EDGE RELAY] Command {cmd_id} ACKed by Pi 4 Gateway.")
            self._send_response(200, {"ok": True, "data": {"id": cmd_id, "status": "ACKED"}})

        # 4. Manual Emergency Alarm Trigger
        elif self.path == '/api/v1/alarms/manual':
            node_id = body.get("nodeId", "ALL")
            cmd = enqueue_local_command("RAISE_ALARM", node_id, {"severity": "CRITICAL"}, body.get("issuedBy", "OPERATOR"))
            self._send_response(201, {"ok": True, "data": {"alarm": {"id": f"ALM-{int(time.time())}"}, "command": cmd}})

        # 5. Resolve Alarm / Clear Actuators
        elif self.path in ('/api/v1/alarms/resolve-active', '/api/v1/alarms/resolve'):
            cmd = enqueue_local_command("CLEAR_ALARM", "ALL", {}, body.get("by", "OPERATOR"))
            self._send_response(200, {"ok": True, "data": {"cleared": True, "command": cmd}})

        elif self.path == '/api/v1/photos':
            self._send_response(200, {"ok": True, "data": {"id": str(uuid.uuid4())}})
            
        else:
            self._send_response(404, {"ok": False, "error": "Not Found"})

def main():
    init_db()
    
    # Start Cloud Command Poller Thread
    t = threading.Thread(target=sync_cloud_commands_loop, daemon=True)
    t.start()
    logger.info("Background Cloud Command Sync Worker started.")

    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, RequestHandler)
    logger.info(f"Starting Edge Gateway (PC Local Receiver) on http://{HOST}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        httpd.server_close()

if __name__ == '__main__':
    main()


