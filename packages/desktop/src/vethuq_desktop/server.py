"""Runs the Flask application on 127.0.0.1 in a background thread."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request

from flask import Flask
from werkzeug.serving import BaseWSGIServer, make_server

from vethuq_api import allow_host

HOST = "127.0.0.1"


class LocalServer:
    """The API on a free loopback port.

    Port 0 asks the operating system for an unused port at bind time, so there is no window between
    "find a free port" and "use it" for another program to take it.
    """

    def __init__(self, app: Flask, *, port: int = 0) -> None:
        self._server: BaseWSGIServer = make_server(HOST, port, app, threaded=True)
        self.port: int = self._server.server_port
        allow_host(app, f"{HOST}:{self.port}")
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="vethuq-api", daemon=True
        )

    @property
    def origin(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self) -> None:
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                with urllib.request.urlopen(f"{self.origin}/api/health", timeout=1) as response:  # noqa: S310
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("The VethuQ API did not become ready")
            time.sleep(0.05)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
