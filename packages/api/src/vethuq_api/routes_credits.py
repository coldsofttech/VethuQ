"""The endpoints for credits."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq.errors import InvalidGrantError
from vethuq_api.core import Core
from vethuq_api.credits_service import CreditsService


def _int(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError as error:
        raise ValueError(f"{name} is a whole number.") from error


def _flag(name: str, default: bool = False) -> bool:
    value = request.args.get(name)
    return default if value is None else value.lower() in ("1", "true", "yes")


def _opt(name: str) -> str | None:
    return request.args.get(name) or None


def _opt_int(name: str) -> int | None:
    return _int(name, 0) if request.args.get(name) else None


def _attachment(data: bytes, name: str, mime: str) -> Response:
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def register(api: Blueprint, core: Core) -> None:
    @api.errorhandler(InvalidGrantError)
    def _invalid(error: InvalidGrantError) -> tuple[Response, int]:
        return jsonify(error=str(error)), 422

    def service() -> CreditsService:
        return core.credits()

    @api.get("/credits/report")
    def credits_report() -> Response:
        return jsonify(service().report())

    @api.get("/credits/summary")
    def credits_summary() -> Response:
        return jsonify(service().summary())

    @api.get("/credits/wallets")
    def credits_wallets() -> Response:
        wallets = service().wallets()
        return jsonify(wallets=wallets, totals=[service().totals(w["wallet"]) for w in wallets])

    def _grant_args() -> dict[str, Any]:
        return {
            "wallet": _opt("wallet"),
            "kind": _opt("kind"),
            "scope": _opt("scope"),
            "include_expired": _flag("expired", True),
            "q": request.args.get("q", ""),
            "sort": request.args.get("sort", "granted_at"),
            "order": request.args.get("order", "desc"),
            "offset": _int("offset", 0),
            "limit": min(_int("limit", 200), 1000),
        }

    @api.get("/credits/grants")
    def credits_grants() -> Response:
        return jsonify(service().grants(**_grant_args()))

    def _usage_args() -> dict[str, Any]:
        return {
            "group_by": request.args.get("group_by", "day"),
            "wallet": _opt("wallet"),
            "source": _opt_int("source"),
            "since": _opt("since"),
            "until": _opt("until"),
            "q": request.args.get("q", ""),
            "sort": request.args.get("sort", "key"),
            "order": request.args.get("order", "desc"),
            "offset": _int("offset", 0),
            "limit": min(_int("limit", 200), 1000),
        }

    @api.get("/credits/usage")
    def credits_usage() -> Response:
        return jsonify(service().usage(**_usage_args()))

    @api.get("/credits/daily")
    def credits_daily() -> Response:
        return jsonify(service().daily(min(max(_int("days", 30), 1), 366)))

    def _ledger_args() -> dict[str, Any]:
        return {
            "kind": _opt("kind"),
            "wallet": _opt("wallet"),
            "source": _opt_int("source"),
            "run": _opt_int("run"),
            "since": _opt("since"),
            "until": _opt("until"),
            "sort": request.args.get("sort", "at"),
            "order": request.args.get("order", "desc"),
            "offset": _int("offset", 0),
            "limit": min(_int("limit", 100), 1000),
        }

    @api.get("/credits/ledger")
    def credits_ledger() -> Response:
        return jsonify(service().ledger(**_ledger_args()))

    @api.get("/credits/export/<what>")
    def credits_export(what: str) -> Response:
        fmt = request.args.get("format", "csv")
        if what == "grants":
            args = {**_grant_args(), "offset": 0, "limit": 100000}
            rows = service().grants(**args)["items"]
        elif what == "usage":
            args = {**_usage_args(), "offset": 0, "limit": 100000}
            rows = service().usage(**args)["items"]
        elif what == "ledger":
            args = {**_ledger_args(), "offset": 0, "limit": 100000}
            rows = service().ledger(**args)["items"]
        else:
            return jsonify(error="Export grants, usage or ledger."), 404
        return _attachment(*service().export(rows, fmt, f"credits-{what}"))

    @api.post("/credits/redeem")
    def credits_redeem() -> Response:
        body = request.get_json(silent=True)
        token = body.get("token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Paste the licence.")
        return jsonify(redeemed=service().redeem(token.strip()))
