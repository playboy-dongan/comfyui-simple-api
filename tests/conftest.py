import base64
import io
import json
from collections import deque
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import torch
from PIL import Image


@pytest.fixture
def image():
    return torch.linspace(0, 1, 8 * 6 * 3).reshape(1, 8, 6, 3)


@pytest.fixture
def image_b64():
    output = io.BytesIO()
    Image.new("RGB", (7, 5), "orange").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


@pytest.fixture
def api_server(monkeypatch):
    """Real local HTTP requests, including requests-generated multipart bodies."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    received, replies = [], deque()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.do_POST()

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            content_type = self.headers.get("Content-Type", "")
            body, multipart = None, []
            if content_type.startswith("application/json"):
                body = json.loads(raw)
            elif content_type.startswith("multipart/"):
                parsed = BytesParser(policy=default).parsebytes(
                    ("Content-Type: " + content_type + "\r\n\r\n").encode() + raw
                )
                for part in parsed.iter_parts():
                    multipart.append(
                        {
                            "name": part.get_param(
                                "name", header="content-disposition"
                            ),
                            "filename": part.get_filename(),
                            "data": part.get_payload(decode=True),
                        }
                    )
            received.append(
                {
                    "path": self.path,
                    "method": self.command,
                    "headers": self.headers,
                    "json": body,
                    "multipart": multipart,
                }
            )
            status, value, extra_headers = (
                replies.popleft() if replies else (200, {}, {})
            )
            raw_reply = (
                value if isinstance(value, bytes) else json.dumps(value).encode()
            )
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json"
                if not isinstance(value, bytes)
                else "application/octet-stream",
            )
            for key, value in extra_headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw_reply)))
            self.end_headers()
            self.wfile.write(raw_reply)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()

    class API:
        url = f"http://127.0.0.1:{server.server_port}"
        requests = received

        def reply(self, value, status=200, headers=None):
            replies.append((status, value, headers or {}))

    try:
        yield API()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
