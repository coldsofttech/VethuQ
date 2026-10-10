"""Helpers for the policy tests: signing keys, signed envelopes and a local policy server."""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from vethuq_core.policy import PolicyKey


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class PolicySigner:
    """A throwaway signing key that produces envelopes the way the admin tool would."""

    def __init__(self, kid: str, standby: bool = False) -> None:
        self.kid = kid
        self.standby = standby
        self._private = Ed25519PrivateKey.generate()

    def key(self) -> PolicyKey:
        public = self._private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return PolicyKey(self.kid, public, self.standby)

    def payload(self, sequence: int = 1, **extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "schema_version": 1,
            "sequence": sequence,
            "issued_at": "2026-10-08T12:00:00Z",
            "kid": self.kid,
            "versions": {
                "desktop": {"latest": "1.2.0", "minimum_supported": "1.0.0"},
                "pip": {"latest": "1.2.0", "minimum_supported": "1.0.0"},
            },
        }
        return {**base, **extra}

    def envelope(self, content: dict[str, Any] | None = None, **fields: Any) -> bytes:
        """A signed envelope; `fields` override envelope members (e.g. `kid=`, `sig=`)."""
        data = json.dumps(content if content is not None else self.payload()).encode("utf-8")
        envelope = {
            "alg": "Ed25519",
            "kid": self.kid,
            "payload": b64url(data),
            "sig": b64url(self._private.sign(data)),
        }
        envelope.update(fields)
        return json.dumps(envelope).encode("utf-8")


class PolicyServer:
    """A local HTTP server with a scripted response per path, recording each request."""

    def __init__(self) -> None:
        self.responses: dict[str, tuple[int, bytes, dict[str, str]]] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.requests.append((self.path, {k: v for k, v in self.headers.items()}))
                status, body, headers = owner.responses.get(self.path, (404, b"", {}))
                etag = headers.get("ETag")
                if etag and self.headers.get("If-None-Match") == etag:
                    status, body = 304, b""
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> PolicyServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def url(self, path: str = "/v1/policy.json") -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}{path}"

    def serve(self, path: str, body: bytes, status: int = 200, **headers: str) -> None:
        self.responses[path] = (status, body, headers)
