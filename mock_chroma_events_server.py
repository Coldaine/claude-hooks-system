#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

LOG_FILE = Path("mock_chroma_events.jsonl")

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            json.loads(body.decode("utf-8"))
        except Exception:
            # still log raw body
            pass

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("ab") as f:
            f.write(body + b"\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, fmt, *args):
        # Keep stdout clean
        return

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 9000), Handler)
    print("Mock Chroma/Zo event server on http://127.0.0.1:9000")
    server.serve_forever()

