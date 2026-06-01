import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from gpiozero import DistanceSensor
from time import sleep

# Initialize sensor
sensor = DistanceSensor(echo=27, trigger=17, max_distance=4.0)

# Global variable for distance
current_distance = 0.0

# Measurement loop (runs in background thread)
def measure_loop():
    global current_distance
    while True:
        current_distance = sensor.distance * 100  # Convert meters to cm
        sleep(0.2)  # Update (in seconds)

# HTTP handler for /distance
class DistanceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/distance':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')  # Allow browser access from any origin
            self.end_headers()
            self.wfile.write(f"{current_distance:.2f}".encode('utf-8'))
        else:
            self.send_error(404, 'Not Found')

# Server runner
def run_server():
    server_address = ('0.0.0.0', 5000)  # Bind to all interfaces (network-accessible)
    httpd = HTTPServer(server_address, DistanceHandler)
    print("Sensor server running on port 5000")
    httpd.serve_forever()

# Start measurement thread
threading.Thread(target=measure_loop, daemon=True).start()

# Run server in main thread
run_server()
