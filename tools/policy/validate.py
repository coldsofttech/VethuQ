#!/usr/bin/env python3
"""Validate VethuQ policy files. Needs only public keys; no secrets.

  python tools/policy/validate.py envelope FILE --keys-dir policy/keys [--previous PREV_FILE]
  python tools/policy/validate.py payload FILE

`envelope` checks: envelope schema, Ed25519 signature against keys/<kid>.pub, payload schema,
semantic rules (windows, versions, kid match) and, if --previous is given and the file
changed, that sequence is strictly greater than the previous one.
`payload` checks only the payload schema and semantic rules (used for unsigned examples).

Exit code 0 = valid, 1 = invalid. A file that is exactly the documented unsigned
placeholder (`"_placeholder": true`) is accepted with a warning until the first signed policy lands.
"""

import argparse
import base64
import binascii
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

# The policy files live in `policy/` at the repository root.
ROOT = Path(__file__).resolve().parents[2] / "policy"


class PolicyError(Exception):
    pass


class PolicyValidator:
    """Validates payloads and signed envelopes for policy schema v1."""

    KID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
    SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
    TZ_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

    def __init__(self, keys_dir=ROOT / "keys", schema_dir=ROOT / "schema" / "v1"):
        self.keys_dir = Path(keys_dir)
        self.schema_dir = Path(schema_dir)
        self._schemas = {}

    # ---- loading helpers -------------------------------------------------

    @staticmethod
    def load_json(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PolicyError(f"cannot read {path}: {e}") from e

    @staticmethod
    def b64url_decode(s):
        try:
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        except (binascii.Error, ValueError) as e:
            raise PolicyError(f"invalid base64url: {e}") from e

    @staticmethod
    def is_placeholder(doc):
        return isinstance(doc, dict) and doc.get("_placeholder") is True and "sig" not in doc

    def load_key(self, kid):
        if not self.KID_RE.match(kid):
            raise PolicyError(f"invalid kid {kid!r}")
        path = self.keys_dir / f"{kid}.pub"
        if not path.is_file():
            raise PolicyError(f"no public key for kid {kid!r} (expected {path})")
        raw = self.b64url_decode(path.read_text(encoding="utf-8").strip())
        if len(raw) != 32:
            raise PolicyError(f"{path}: Ed25519 public key must be 32 bytes, got {len(raw)}")
        return Ed25519PublicKey.from_public_bytes(raw)

    # ---- schema ----------------------------------------------------------

    def schema_errors(self, instance, schema_name):
        if schema_name not in self._schemas:
            schema = json.loads((self.schema_dir / schema_name).read_text(encoding="utf-8"))
            self._schemas[schema_name] = Draft202012Validator(schema)
        validator = self._schemas[schema_name]
        return [
            f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
        ]

    # ---- semantic rules --------------------------------------------------

    def parse_time(self, value, where):
        """Strict RFC 3339 parse; rejects impossible dates like Feb 30 and missing timezones."""
        if not isinstance(value, str) or not self.TZ_RE.search(value):
            raise PolicyError(f"{where}: timestamp must be RFC 3339 with a timezone: {value!r}")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise PolicyError(f"{where}: impossible or malformed date: {value!r}") from None

    def _semver(self, s):
        return tuple(int(x) for x in self.SEMVER_RE.match(s).groups())

    def _check_window(self, obj, where, required):
        s, e = obj.get("starts_at"), obj.get("ends_at")
        start = self.parse_time(s, f"{where}.starts_at") if s is not None else None
        end = self.parse_time(e, f"{where}.ends_at") if e is not None else None
        if required and (start is None or end is None):
            raise PolicyError(f"{where}: starts_at and ends_at are required")
        if start and end and not start < end:
            raise PolicyError(f"{where}: starts_at must be before ends_at ({s} >= {e})")

    @staticmethod
    def _collect(errs, fn):
        try:
            fn()
        except PolicyError as e:
            errs.append(str(e))

    def semantic_errors(self, p):
        errs = []
        self._collect(errs, lambda: self.parse_time(p.get("issued_at"), "issued_at"))
        for i, n in enumerate(p.get("notices") or []):
            self._collect(errs, lambda n=n, i=i: self._check_window(n, f"notices[{i}]", False))
        for i, lim in enumerate(p.get("limits") or []):
            self._collect(errs, lambda lim=lim, i=i: self._check_window(lim, f"limits[{i}]", True))
        for dist, d in (p.get("versions") or {}).items():
            try:
                if self._semver(d["minimum_supported"]) > self._semver(d["latest"]):
                    errs.append(f"versions.{dist}: minimum_supported is greater than latest")
            except (KeyError, AttributeError, TypeError):
                pass  # reported by the schema check
        addon = (p.get("compatibility") or {}).get("addon_api")
        if addon:
            try:
                if self._semver(addon["min"]) > self._semver(addon["max"]):
                    errs.append("compatibility.addon_api: min is greater than max")
            except (KeyError, AttributeError, TypeError):
                pass
        errs += self.credit_errors(p)
        errs += self.revocation_errors(p)
        return errs

    # ---- key revocation ----------------------------------------------------------

    def revocation_errors(self, p):
        """revoked_key_ids: a policy may not revoke its own signing key. (Which keys may sign a
        revocation is a client rule, based on the client's embedded standby set.)"""
        errs = []
        revoked = p.get("revoked_key_ids") or []
        if p.get("kid") in revoked:
            errs.append(f"revoked_key_ids: a policy cannot revoke its own signing key {p['kid']!r}")
        return errs

    # ---- credits sections (rate card, wallets, promotions, caps, metrics) -------

    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    DEFAULT_METRICS_BONUS_CAP = 15
    CREDIT_SECTIONS = ("rate_card", "wallets", "caps")

    def parse_date(self, value, where):
        """Strict YYYY-MM-DD (whole UTC days); rejects impossible dates like Feb 30."""
        if not isinstance(value, str) or not self.DATE_RE.match(value):
            raise PolicyError(f"{where}: must be a UTC date YYYY-MM-DD: {value!r}")
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise PolicyError(f"{where}: impossible or malformed date: {value!r}") from None

    @staticmethod
    def _decimal_places_ok(value):
        return isinstance(value, (int, float)) and abs(value * 1000 - round(value * 1000)) < 1e-9

    def _check_decimals(self, node, where, errs):
        """Credit amounts have at most 3 decimal places (clients use integer millicredits)."""
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("percent", "tolerance_percent", "reference_megapixels", "step"):
                    continue  # not credit amounts
                self._check_decimals(value, f"{where}.{key}", errs)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                self._check_decimals(value, f"{where}[{i}]", errs)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and not self._decimal_places_ok(node):
            errs.append(f"{where}: more than 3 decimal places: {node!r}")

    def _check_scope(self, obj, where, errs):
        client = ((obj or {}).get("applies_to") or {}).get("client") or {}
        try:
            if "min" in client and "max" in client and self._semver(client["min"]) > self._semver(client["max"]):
                errs.append(f"{where}.applies_to.client: min is greater than max")
        except (AttributeError, TypeError):
            pass  # reported by the schema check

    def credit_errors(self, p):
        errs = []
        if "effective_from" in p:
            self._collect(errs, lambda: self.parse_date(p["effective_from"], "effective_from"))
        self._check_scope(p, "<payload>", errs)
        for name in self.CREDIT_SECTIONS:
            if name in p:
                self._check_decimals(p[name], name, errs)
        for name in ("rate_card", "wallets", "ocr"):
            if isinstance(p.get(name), dict):
                self._check_scope(p[name], name, errs)

        caps = p.get("caps") or {}
        seen = set()
        for i, promo in enumerate(p.get("promotions") or []):
            where = f"promotions[{i}]"
            if promo["id"] in seen:
                errs.append(f"{where}: duplicate promotion id {promo['id']!r}")
            seen.add(promo["id"])
            window = {}
            for field in ("start_date", "end_date"):
                try:
                    window[field] = self.parse_date(promo[field], f"{where}.{field}")
                except PolicyError as e:
                    errs.append(str(e))
            if len(window) == 2 and window["start_date"] > window["end_date"]:
                errs.append(
                    f"{where}: start_date must not be after end_date ({promo['start_date']} > {promo['end_date']})"
                )
            self._check_scope(promo, where, errs)
            limit = caps.get("promotion_uplift_percent")
            for wallet, uplift in promo["uplift"].items():
                self._check_decimals(uplift.get("absolute"), f"{where}.uplift.{wallet}.absolute", errs)
                if limit is not None and uplift.get("percent", 0) > limit:
                    errs.append(
                        f"{where}.uplift.{wallet}: percent {uplift['percent']} exceeds "
                        f"caps.promotion_uplift_percent {limit}"
                    )

        bonus = (p.get("metrics") or {}).get("bonus_percent")
        bonus_cap = caps.get("metrics_bonus_percent", self.DEFAULT_METRICS_BONUS_CAP)
        if bonus is not None and bonus > bonus_cap:
            errs.append(f"metrics.bonus_percent {bonus} exceeds the metrics bonus cap {bonus_cap}")
        return errs

    # ---- public checks ---------------------------------------------------

    def validate_payload(self, payload):
        errs = self.schema_errors(payload, "policy.schema.json")
        return errs if errs else self.semantic_errors(payload)

    def check_sequence(self, payload, previous_doc):
        """previous_doc is the previous commit's policy.json (parsed). Skipped if it is a placeholder."""
        if self.is_placeholder(previous_doc):
            return []
        try:
            prev_seq = json.loads(self.b64url_decode(previous_doc["payload"]).decode("utf-8"))["sequence"]
        except (KeyError, TypeError, ValueError, PolicyError):
            return []  # previous file unreadable: nothing to compare against
        if not payload["sequence"] > prev_seq:
            return [f"sequence {payload['sequence']} must be strictly greater than previous {prev_seq}"]
        return []

    def validate_envelope(self, env, previous=None):
        """Return (errors, payload_or_None)."""
        errs = self.schema_errors(env, "envelope.schema.json")
        if errs:
            return errs, None
        try:
            key = self.load_key(env["kid"])
            payload_bytes = self.b64url_decode(env["payload"])
            sig = self.b64url_decode(env["sig"])
            if len(sig) != 64:
                return [f"signature must be 64 bytes, got {len(sig)}"], None
            key.verify(sig, payload_bytes)
        except InvalidSignature:
            return ["signature does not verify against the published key"], None
        except PolicyError as e:
            return [str(e)], None
        # Only parse the payload after the signature verified.
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except ValueError as e:
            return [f"payload is not valid UTF-8 JSON: {e}"], None
        errs = self.validate_payload(payload)
        if not errs and payload.get("kid") != env["kid"]:
            errs.append(f"payload.kid {payload.get('kid')!r} != envelope kid {env['kid']!r}")
        if not errs and previous is not None:
            errs += self.check_sequence(payload, previous)
        return errs, payload

    def validate_file(self, mode, path, previous_path=None):
        """Validate a file for the CLI. Returns (errors, warnings)."""
        doc = self.load_json(path)
        if mode == "payload":
            return self.validate_payload(doc), []
        if self.is_placeholder(doc):
            return [], ["unsigned placeholder accepted; replace with signed output"]
        previous = None
        if previous_path and Path(previous_path).is_file():
            previous = self.load_json(previous_path)
            if previous == doc:
                previous = None  # unchanged file: no sequence bump required
        return self.validate_envelope(doc, previous)[0], []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    e = sub.add_parser("envelope")
    e.add_argument("file")
    e.add_argument("--keys-dir", default=str(ROOT / "keys"))
    e.add_argument("--previous", help="previous commit's policy.json; if given and different, sequence must increase")
    pl = sub.add_parser("payload")
    pl.add_argument("file")
    a = ap.parse_args(argv)

    validator = PolicyValidator(keys_dir=getattr(a, "keys_dir", ROOT / "keys"))
    try:
        errs, warnings = validator.validate_file(a.mode, a.file, getattr(a, "previous", None))
    except PolicyError as ex:
        errs, warnings = [str(ex)], []
    for w in warnings:
        print(f"WARNING {a.file}: {w}", file=sys.stderr)
    for m in errs:
        print(f"ERROR {a.file}: {m}", file=sys.stderr)
    if errs:
        return 1
    print(f"OK {a.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
