from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class ProfileFixtureHandler(BaseHTTPRequestHandler):
    server_version = "ProfileFixture/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _write_json(self, status: int, payload: dict, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_html(self) -> None:
        body = Path(__file__).with_name("index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/refresh":
            self.server.state["valid_token"] = "token-2"  # type: ignore[attr-defined]
            self._write_json(200, {"access_token": "token-2"})
            return
        self._write_json(404, {"error": "not_found"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._write_html()
            return
        if parsed.path != "/profiles":
            self._write_json(404, {"error": "not_found"})
            return

        auth = self.headers.get("Authorization", "")
        valid_token = self.server.state.get("valid_token", "token-2")  # type: ignore[attr-defined]
        if auth != f"Bearer {valid_token}":
            self._write_json(401, {"error": "session_expired"})
            return

        query = parse_qs(parsed.query)
        cursor = query.get("cursor", [""])[0]

        page2_attempts = self.server.state.setdefault("page2_attempts", 0)  # type: ignore[attr-defined]
        if cursor == "page2" and page2_attempts == 0:
            self.server.state["page2_attempts"] = 1  # type: ignore[attr-defined]
            self._write_json(429, {"error": "rate_limited"}, {"Retry-After": "0"})
            return

        if cursor == "":
            self._write_json(
                200,
                {
                    "profiles": [
                        {"id": "p1", "name": "Alice", "title": "Engineer"},
                        {"id": "p2", "name": "Bob", "title": "Designer"},
                    ],
                    "next_cursor": "page2",
                },
            )
            return

        if cursor == "page2":
            self._write_json(
                200,
                {
                    "profiles": [
                        {"id": "p2", "name": "Bob", "title": "Designer duplicate"},
                        {"id": "p3", "name": "Carol", "title": "Manager"},
                    ],
                    "next_cursor": "page3",
                },
            )
            return

        if cursor == "page3":
            self._write_json(
                200,
                {
                    "profiles": [
                        {"id": "p4", "title": "Missing name should be rejected"},
                    ],
                    "next_cursor": "page2",
                },
            )
            return

        self._write_json(200, {"profiles": [], "next_cursor": ""})


class FixtureServer:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProfileFixtureHandler)
        self.httpd.state = {"valid_token": "token-2"}  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def start(self) -> "FixtureServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def run_forever(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), ProfileFixtureHandler)
    server.state = {"valid_token": "token-2"}  # type: ignore[attr-defined]
    print(f"http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run_forever()
