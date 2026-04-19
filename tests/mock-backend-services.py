#!/usr/bin/env python3
"""
Mock backend services for gateway routing tests.
Listens on multiple ports and echoes back the expected service name.
"""

import http.server
import socketserver
import threading
import json

class MockHandler(http.server.BaseHTTPRequestHandler):
    service_name = "unknown"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"service": self.service_name, "path": self.path}).encode())

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode() if length else "{}"
        self.wfile.write(json.dumps({"service": self.service_name, "path": self.path, "body": body}).encode())

    def log_message(self, format, *args):
        pass


def make_server(port, name):
    class Handler(MockHandler):
        service_name = name
    httpd = socketserver.TCPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


servers = {
    3001: "nodejs",
    8000: "python",
    8002: "retrieval",
    8081: "websocket",
    8001: "ocr",
    8003: "llm",
}

running = []
for port, name in servers.items():
    running.append(make_server(port, name))

print("Mock backends ready on ports:", list(servers.keys()))
try:
    while True:
        pass
except KeyboardInterrupt:
    pass
