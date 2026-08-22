#!/usr/bin/env python3
"""
PC Local Receiver
Lightweight HTTP server running on the user's PC to receive telemetry
from the Raspberry Pi forwarder and store it in a local SQLite database.
"""

import os
import json
import uuid
import sqlite3
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
HOST = '0.0.0.0'
PORT = 4000
DB_PATH = '/home/sparkle/Documents/MINE SIH/mine-iot/pc_telemetry.db'

def init_db():
    """Initialize the SQLite database and create the table if it doesn't exist."""
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create the table with 19 columns + received_at
    # Note: id is auto-incrementing primary key
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
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def insert_reading(node_id, payload, received_at):
    """Insert a single reading into the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Extract common fields
    seq = payload.get('seq')
    ms = payload.get('ms')
    vib = payload.get('vib')
    
    # Extract ADXL / GY87 fields
    adxl = payload.get('adxl345') or payload.get('gy87_mpu') or {}
    adxl_ax = adxl.get('ax')
    adxl_ay = adxl.get('ay')
    adxl_az = adxl.get('az')
    
    # Extract MPU fields
    mpu = payload.get('mpu6050') or {}
    mpu_ax = mpu.get('ax')
    mpu_ay = mpu.get('ay')
    mpu_az = mpu.get('az')
    mpu_gx = mpu.get('gx')
    mpu_gy = mpu.get('gy')
    mpu_gz = mpu.get('gz')
    
    # Extract other fields
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

class RequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        """Send CORS headers."""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def _send_response(self, status_code, payload):
        """Helper to send JSON responses."""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))
        
    def do_OPTIONS(self):
        """Handle OPTIONS request for CORS."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/health':
            self._send_response(200, {"ok": True, "service": "pc-local-receiver"})
        
        elif self.path == '/api/v1/commands/pending':
            self._send_response(200, {"ok": True, "data": []})
            
        else:
            self._send_response(404, {"ok": False, "error": "Not Found"})

    def do_POST(self):
        """Handle POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            body = json.loads(post_data.decode('utf-8'))
        except json.JSONDecodeError:
            self._send_response(400, {"ok": False, "error": "Invalid JSON"})
            return

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
                    
            logger.info(f"Ingested {len(results)} readings")
            self._send_response(200, {"ok": True, "results": results})
            
        elif self.path == '/api/v1/photos':
            logger.info(f"Received photo metadata: {body}")
            self._send_response(200, {"ok": True, "data": {"id": str(uuid.uuid4())}})
            
        else:
            self._send_response(404, {"ok": False, "error": "Not Found"})

def main():
    init_db()
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, RequestHandler)
    logger.info(f"Starting PC Local Receiver on http://{HOST}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        httpd.server_close()

if __name__ == '__main__':
    main()
