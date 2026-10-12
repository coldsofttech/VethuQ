"""Request checks that keep other local programs and web pages out of the API."""

from __future__ import annotations

import hmac
import secrets
import threading

from flask import Flask, Response, jsonify, request

SESSION_COOKIE = "vethuq_session"
BOOTSTRAP_PARAM = "t"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Fluent UI writes its styles at run time, so styles may be inline; scripts may not.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
# Reachable without a session: the readiness probe, which only ever says "ok".
_PUBLIC_API_PATHS = frozenset({"/api/health"})


class SessionGate:
    """Exchanges the one-time start-up token for session ids, and recognises those ids."""

    def __init__(self, bootstrap_token: str) -> None:
        self._token: str | None = bootstrap_token
        self._sessions: set[str] = set()
        self._lock = threading.Lock()

    def redeem(self, candidate: str) -> str | None:
        """Return a new session id for the start-up token, once; None for anything else."""
        with self._lock:
            token = self._token
            if token is None or not hmac.compare_digest(token.encode(), candidate.encode()):
                return None
            self._token = None
            session_id = secrets.token_urlsafe(32)
            self._sessions.add(session_id)
            return session_id

    def is_valid(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            return any(
                hmac.compare_digest(known.encode(), session_id.encode()) for known in self._sessions
            )


def _forbidden(message: str) -> tuple[Response, int]:
    return jsonify(error=message), 403


def install(app: Flask, gate: SessionGate) -> None:
    """Add the Host, Origin and session checks and the security headers to `app`."""

    @app.before_request
    def _check_request() -> tuple[Response, int] | None:
        allowed: set[str] = app.config["ALLOWED_HOSTS"]
        if request.host not in allowed:
            return _forbidden("Unexpected Host")
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin is None or origin not in {f"http://{host}" for host in allowed}:
                return _forbidden("Unexpected Origin")
        if request.path.startswith("/api/") and request.path not in _PUBLIC_API_PATHS:
            if not gate.is_valid(request.cookies.get(SESSION_COOKIE)):
                return jsonify(error="Not signed in"), 401
        return None

    @app.after_request
    def _add_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
