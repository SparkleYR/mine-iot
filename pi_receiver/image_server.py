#!/usr/bin/env python3
import os
import sys
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Directory where uploaded images will be saved
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captured_images")

class ImageUploadHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/upload":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Empty payload")
                return

            # Read JPEG image bytes
            image_data = self.rfile.read(content_length)
            
            # Ensure target directory exists
            os.makedirs(SAVE_DIR, exist_ok=True)

            # Generate timestamp filename: YYYYMMDD_HHMMSS_microseconds.jpg
            now = datetime.datetime.now()
            filename = f"img_{now.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(SAVE_DIR, filename)

            # Write image to disk
            with open(filepath, "wb") as f:
                f.write(image_data)

            log_entry = f"[{now.isoformat()}] Saved: {filename} ({len(image_data)} bytes)"
            print(log_entry)

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Saved: {filename}".encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Override to suppress standard HTTP access logs
        return

def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    server_address = ('', 5000)
    httpd = HTTPServer(server_address, ImageUploadHandler)
    print("==================================================")
    print(" ESP32-CAM Image Upload Receiver")
    print("==================================================")
    print(f"Listening on port 5000...")
    print(f"Saving captured images to: {SAVE_DIR}")
    print("==================================================")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Image Server... Goodbye!")
        httpd.server_close()

if __name__ == "__main__":
    main()
