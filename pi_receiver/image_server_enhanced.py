#!/usr/bin/env python3

import os
import json
import base64
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Paths - using the script's directory as the base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, 'captured_images')
LOG_FILE = os.path.join(BASE_DIR, 'image_server.log')

# Endpoints
PC_UPLOAD_URL = "http://192.168.1.1:5000/upload"
API_URL_NGROK = "https://commute-overrule-employer.ngrok-free.dev/api/v1/photos"
API_URL_LOCAL = "http://192.168.1.1:4000/api/v1/photos"

# Ensure directories exist
os.makedirs(IMAGE_DIR, exist_ok=True)

# Configure logging to file and stdout
logger = logging.getLogger('ImageServer')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File handler
fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

def forward_to_pc(jpeg_data):
    """Forwards the raw JPEG bytes to the PC."""
    try:
        logger.info(f"Forwarding image to PC: {PC_UPLOAD_URL}")
        req = urllib.request.Request(
            PC_UPLOAD_URL,
            data=jpeg_data,
            headers={'Content-Type': 'image/jpeg'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            logger.info(f"PC forward response: {response.getcode()}")
    except Exception as e:
        logger.error(f"Failed to forward to PC: {e}")

def register_with_api(api_url, payload_json):
    """Registers the photo with the backend API."""
    try:
        logger.info(f"Registering with API: {api_url}")
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'ngrok-skip-browser-warning': '1',
            'User-Agent': 'MinePi4-ImageServer/1.0'
        }
        req = urllib.request.Request(
            api_url,
            data=payload_json,
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            logger.info(f"API registration response from {api_url}: {response.getcode()}")
    except Exception as e:
        logger.error(f"Failed to register with API {api_url}: {e}")

def process_image(jpeg_data):
    """Processes the image asynchronously."""
    # 1. Save locally
    now = datetime.now()
    timestamp_str = now.strftime('%Y%m%d_%H%M%S')
    microseconds = now.strftime('%f')
    filename = f"img_{timestamp_str}_{microseconds}.jpg"
    filepath = os.path.join(IMAGE_DIR, filename)
    
    try:
        with open(filepath, 'wb') as f:
            f.write(jpeg_data)
        logger.info(f"Saved locally: {filepath}")
    except Exception as e:
        logger.error(f"Failed to save locally: {e}")
        return  # Cannot proceed if we don't have the file

    # 2. Forward to PC
    t_forward = threading.Thread(target=forward_to_pc, args=(jpeg_data,))
    t_forward.start()

    # 3. Register with API
    image_b64 = base64.b64encode(jpeg_data).decode('utf-8')
    image_url = f"/photos/{filename}"
    metadata = {
        "title": f"ESP32-CAM Capture {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "imageBase64": image_b64,
        "imageUrl": image_url,
        "thumbnailUrl": image_url,
        "nodeId": "ESP-NODE-01",
        "location": "Underground Gallery",
        "category": "INSPECTION",
        "metadata": {
            "sizeBytes": len(jpeg_data),
            "source": "esp32-cam-auto",
            "resolution": "640x480"
        }
    }
    
    payload_json = json.dumps(metadata).encode('utf-8')
    
    t_api_ngrok = threading.Thread(target=register_with_api, args=(API_URL_NGROK, payload_json))
    t_api_ngrok.start()

    t_api_local = threading.Thread(target=register_with_api, args=(API_URL_LOCAL, payload_json))
    t_api_local.start()

class ImageServerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No content")
            return
            
        jpeg_data = self.rfile.read(content_length)
        
        # Respond immediately to unblock the ESP32-CAM
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
        
        # Process asynchronously
        threading.Thread(target=process_image, args=(jpeg_data,)).start()

    def log_message(self, format, *args):
        # Override to use the standard logger
        logger.info("%s - - [%s] %s" % (
            self.client_address[0],
            self.log_date_time_string(),
            format % args
        ))

def run(server_class=ThreadingHTTPServer, handler_class=ImageServerHandler, port=5000):
    server_address = ('0.0.0.0', port)
    httpd = server_class(server_address, handler_class)
    logger.info(f"Starting multi-threaded image server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logger.info("Server stopped.")

if __name__ == '__main__':
    run()
