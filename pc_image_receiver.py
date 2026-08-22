#!/usr/bin/env python3
import os
import sys
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Local PC save directory
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_receiver", "captured_images")

class PCImageReceiverHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/upload":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Empty payload")
                return

            # Read JPEG binary bytes
            image_data = self.rfile.read(content_length)
            
            # Ensure target directory exists on PC
            os.makedirs(SAVE_DIR, exist_ok=True)

            # Generate timestamp filename: YYYYMMDD_HHMMSS_microseconds.jpg
            now = datetime.datetime.now()
            filename = f"img_{now.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(SAVE_DIR, filename)

            # Write image to PC disk
            with open(filepath, "wb") as f:
                f.write(image_data)

            log_entry = f"[{now.isoformat()}] SAVED ON PC: {filename} ({len(image_data)} bytes)"
            print(log_entry)

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Saved on PC: {filename}".encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress standard HTTP request logs
        return

def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    server_address = ('0.0.0.0', 5000)
    httpd = HTTPServer(server_address, PCImageReceiverHandler)
    print("==================================================")
    print(" PC Image Receiver (Receiving via Pi Proxy)")
    print("==================================================")
    print("Listening on 0.0.0.0:5000 (Ethernet IP: 192.168.1.1)...")
    print(f"Saving images directly to PC folder: {SAVE_DIR}")
    print("==================================================")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PC Image Receiver... Goodbye!")
        httpd.server_close()

if __name__ == "__main__":
    main()
