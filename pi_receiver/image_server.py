#!/usr/bin/env python3
import os
import sys
import datetime
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# PC IP and upload endpoint over ethernet
PC_UPLOAD_URL = "http://192.168.1.1:5000/upload"

class ImageProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/upload":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Empty payload")
                return

            # Read JPEG image bytes directly into RAM (zero disk storage on Pi)
            image_data = self.rfile.read(content_length)
            
            now = datetime.datetime.now()
            print(f"[{now.isoformat()}] Received {len(image_data)} bytes from ESP32-CAM. Forwarding to PC at {PC_UPLOAD_URL}...")

            # Forward the JPEG bytes directly to PC via HTTP POST
            try:
                req = urllib.request.Request(
                    PC_UPLOAD_URL,
                    data=image_data,
                    headers={'Content-Type': 'image/jpeg'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    res_body = response.read().decode('utf-8')
                    print(f"[{now.isoformat()}] Successfully forwarded to PC! Response: {res_body}")
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(f"Forwarded to PC: {res_body}".encode('utf-8'))
            except urllib.error.URLError as e:
                print(f"[{now.isoformat()}] ERROR: Failed to forward image to PC: {e}", file=sys.stderr)
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"PC server unreachable")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default HTTP access logs
        return

def main():
    server_address = ('', 5000)
    httpd = HTTPServer(server_address, ImageProxyHandler)
    print("==================================================")
    print(" Pi Image Proxy Server (ESP32-CAM -> Pi -> PC)")
    print("==================================================")
    print("Listening on port 5000...")
    print(f"Target PC Forwarding URL: {PC_UPLOAD_URL}")
    print("Note: Images are held ONLY in RAM and forwarded directly to PC.")
    print("==================================================")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Pi Proxy Server... Goodbye!")
        httpd.server_close()

if __name__ == "__main__":
    main()
