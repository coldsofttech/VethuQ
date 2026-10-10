import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.policy import validate as vp

ROOT = Path(__file__).resolve().parents[3] / "policy"

KID = "test-1"


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_payload(**over):
    p = json.loads((ROOT / "examples/v1/minimal.payload.json").read_text())
    p["kid"] = KID
    p.update(over)
    return p


class Signer:
    """Ephemeral test key: generated per test, never written to the repo."""

    def __init__(self, keys_dir):
        self.private_key = Ed25519PrivateKey.generate()
        pub = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.keys_dir = keys_dir
        keys_dir.mkdir()
        (keys_dir / f"{KID}.pub").write_text(b64(pub))

    def sign(self, payload, kid=KID, key=None):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        key = key or self.private_key
        return {"alg": "Ed25519", "kid": kid, "payload": b64(raw), "sig": b64(key.sign(raw))}


class ValidatorTestCase:
    """Shared fixtures and helpers."""

    @pytest.fixture
    def signer(self, tmp_path):
        return Signer(tmp_path / "keys")

    @pytest.fixture
    def validator(self, signer):
        return vp.PolicyValidator(keys_dir=signer.keys_dir)

    @staticmethod
    def envelope_errors(validator, env, prev=None):
        return validator.validate_envelope(env, prev)[0]


class TestExamples:
    validator = vp.PolicyValidator()

    def test_example_payloads_pass(self):
        files = list((ROOT / "examples/v1").glob("*.payload.json"))
        assert files
        for f in files:
            assert self.validator.validate_payload(json.loads(f.read_text())) == [], f.name

    def test_example_envelope_matches_envelope_schema(self):
        env = json.loads((ROOT / "examples/v1/envelope.example.json").read_text())
        assert self.validator.schema_errors(env, "envelope.schema.json") == []


class TestSchema(ValidatorTestCase):
    def test_valid_envelope_passes(self, signer, validator):
        assert self.envelope_errors(validator, signer.sign(make_payload())) == []

    def test_schema_violation(self, signer, validator):
        p = make_payload()
        del p["versions"]
        assert any("versions" in e for e in self.envelope_errors(validator, signer.sign(p)))

    def test_revoked_licence_ids_accepted(self, signer, validator):
        env = signer.sign(make_payload(revoked_licence_ids=["lic-1", "lic-2"]))
        assert self.envelope_errors(validator, env) == []

    @pytest.mark.parametrize("value", [["a", "a"], ["bad id"], [1], "lic-1"])
    def test_bad_revoked_licence_ids_rejected(self, signer, validator, value):
        env = signer.sign(make_payload(revoked_licence_ids=value))
        assert self.envelope_errors(validator, env)

    def test_addons_section_accepted(self, signer, validator):
        addons = {"backup": {"enabled": False, "latest": "1.0.0", "minimum_supported": "0.1.0"}}
        env = signer.sign(make_payload(addons=addons))
        assert self.envelope_errors(validator, env) == []

    def test_bad_addon_version_rejected(self, signer, validator):
        env = signer.sign(make_payload(addons={"backup": {"latest": "one"}}))
        assert self.envelope_errors(validator, env)

    def test_unknown_fields_ignored(self, signer, validator):
        env = signer.sign(make_payload(future_field={"a": 1}))
        assert self.envelope_errors(validator, env) == []

    @pytest.mark.parametrize(
        "field,value",
        [
            ("sha256", "xyz"),
            ("url", "http://example.com/a.exe"),
            ("size", 0),
        ],
    )
    def test_download_format_checks(self, signer, validator, field, value):
        download = {
            "platform": "windows-x64",
            "url": "https://example.com/a.exe",
            "size": 10,
            "sha256": "a" * 64,
        }
        download[field] = value
        p = make_payload()
        p["versions"]["desktop"]["downloads"] = [download]
        assert self.envelope_errors(validator, signer.sign(p))

    def test_minimum_supported_not_above_latest(self, signer, validator):
        p = make_payload()
        p["versions"]["desktop"]["minimum_supported"] = "2.0.0"
        errs = self.envelope_errors(validator, signer.sign(p))
        assert any("minimum_supported" in e for e in errs)


class TestSignature(ValidatorTestCase):
    def test_bad_signature(self, signer, validator):
        env = signer.sign(make_payload(), key=Ed25519PrivateKey.generate())
        assert any("signature" in e for e in self.envelope_errors(validator, env))

    def test_tampered_payload(self, signer, validator):
        env = signer.sign(make_payload())
        env["payload"] = signer.sign(make_payload(sequence=99))["payload"]
        assert any("signature" in e for e in self.envelope_errors(validator, env))

    def test_missing_signature(self, signer, validator):
        env = signer.sign(make_payload())
        del env["sig"]
        assert self.envelope_errors(validator, env)

    def test_unknown_kid(self, signer, validator):
        env = signer.sign(make_payload(kid="other"), kid="other")
        assert any("no public key" in e for e in self.envelope_errors(validator, env))

    def test_kid_mismatch(self, signer, validator):
        env = signer.sign(make_payload(kid="x-2"))
        assert any("kid" in e for e in self.envelope_errors(validator, env))


class TestSequence(ValidatorTestCase):
    def test_sequence_must_increase(self, signer, validator):
        prev = signer.sign(make_payload(sequence=5))
        assert self.envelope_errors(validator, signer.sign(make_payload(sequence=6)), prev) == []
        for seq in (5, 4):
            errs = self.envelope_errors(validator, signer.sign(make_payload(sequence=seq)), prev)
            assert any("strictly greater" in e for e in errs)

    def test_skipped_for_placeholder_previous(self, signer, validator):
        env = signer.sign(make_payload(sequence=1))
        assert self.envelope_errors(validator, env, {"_placeholder": True}) == []


class TestWindows(ValidatorTestCase):
    @pytest.mark.parametrize(
        "starts,ends",
        [
            ("2026-11-02T00:00:00Z", "2026-11-01T00:00:00Z"),  # end before start
            ("2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),  # empty window
            ("2026-02-30T00:00:00Z", "2026-03-01T00:00:00Z"),  # impossible date
            ("2026-11-01", "2026-11-02T00:00:00Z"),  # no time / timezone
        ],
    )
    def test_invalid_notice_window(self, signer, validator, starts, ends):
        notices = [
            {"id": "n", "message": "m", "severity": "info", "starts_at": starts, "ends_at": ends}
        ]
        assert self.envelope_errors(validator, signer.sign(make_payload(notices=notices)))

    def test_limit_window_ordered(self, signer, validator):
        ok = {
            "id": "p",
            "kind": "promotion",
            "starts_at": "2026-11-01T00:00:00Z",
            "ends_at": "2026-11-02T00:00:00Z",
            "adjustments": {"a": 1},
        }
        assert self.envelope_errors(validator, signer.sign(make_payload(limits=[ok]))) == []
        bad = dict(ok, ends_at="2026-10-01T00:00:00Z")
        assert self.envelope_errors(validator, signer.sign(make_payload(limits=[bad])))


class TestCli:
    def test_placeholder_accepted(self, tmp_path):
        f = tmp_path / "policy.json"
        f.write_text('{"_placeholder": true}')
        assert vp.main(["envelope", str(f), "--keys-dir", str(tmp_path)]) == 0

    def test_unsigned_non_placeholder_rejected(self, tmp_path):
        f = tmp_path / "policy.json"
        f.write_text('{"foo": 1}')
        assert vp.main(["envelope", str(f), "--keys-dir", str(tmp_path)]) == 1

    def test_repo_policy_json_passes(self):
        args = ["envelope", str(ROOT / "v1/policy.json"), "--keys-dir", str(ROOT / "keys")]
        assert vp.main(args) == 0


def rate_payload(**sections):
    """A valid payload with the credits sections from the rate-card example, then overrides."""
    p = make_payload()
    p.update(json.loads((ROOT / "examples/v1/with-rate-card.payload.json").read_text()))
    p["kid"] = KID
    p.update(sections)
    return p


class TestCreditsSections(ValidatorTestCase):
    """rate_card, wallets, promotions, caps, grace, metrics, ocr, effective_from, applies_to."""

    def errors(self, signer, validator, **sections):
        return self.envelope_errors(validator, signer.sign(rate_payload(**sections)))

    def test_full_example_is_valid_and_signed_ok(self, signer, validator):
        assert self.errors(signer, validator) == []

    def test_older_payload_without_credits_sections_still_valid(self, signer, validator):
        assert self.envelope_errors(validator, signer.sign(make_payload())) == []

    def test_unknown_fields_inside_new_sections_ignored(self, signer, validator):
        rc = dict(rate_payload()["rate_card"], future_rate=2.5)
        wallets = dict(rate_payload()["wallets"], future_wallet={"daily": 1})
        assert self.errors(signer, validator, rate_card=rc, wallets=wallets) == []

    # ---- effective_from -----------------------------------------------------------------

    @pytest.mark.parametrize(
        "value", ["2026-02-30", "2026-13-01", "2026-10-09T00:00:00Z", "20261009", "tomorrow"]
    )
    def test_effective_from_must_be_a_real_utc_date(self, signer, validator, value):
        assert self.errors(signer, validator, effective_from=value)

    def test_effective_from_optional(self, signer, validator):
        p = rate_payload()
        del p["effective_from"]
        assert self.envelope_errors(validator, signer.sign(p)) == []

    # ---- applies_to ---------------------------------------------------------------------

    def test_absent_applies_to_means_all_versions(self, signer, validator):
        p = rate_payload()
        assert "applies_to" not in p["rate_card"]
        assert self.envelope_errors(validator, signer.sign(p)) == []

    def test_client_range_must_be_ordered(self, signer, validator):
        rc = dict(
            rate_payload()["rate_card"], applies_to={"client": {"min": "2.0.0", "max": "1.0.0"}}
        )
        assert any(
            "min is greater than max" in e for e in self.errors(signer, validator, rate_card=rc)
        )

    def test_payload_level_applies_to_checked(self, signer, validator):
        errs = self.errors(
            signer, validator, applies_to={"client": {"min": "2.0.0", "max": "1.0.0"}}
        )
        assert any("<payload>.applies_to" in e for e in errs)

    def test_open_ended_client_range_ok(self, signer, validator):
        rc = dict(rate_payload()["rate_card"], applies_to={"client": {"min": "1.2.0"}})
        assert self.errors(signer, validator, rate_card=rc) == []

    def test_bad_semver_in_applies_to(self, signer, validator):
        rc = dict(rate_payload()["rate_card"], applies_to={"client": {"min": "one"}})
        assert self.errors(signer, validator, rate_card=rc)

    # ---- rate card ----------------------------------------------------------------------

    def test_rate_card_requires_a_version(self, signer, validator):
        rc = rate_payload()["rate_card"]
        del rc["version"]
        assert self.errors(signer, validator, rate_card=rc)

    @pytest.mark.parametrize("version", [0, -1, 1.5, "3"])
    def test_rate_card_version_must_be_a_positive_integer(self, signer, validator, version):
        rc = dict(rate_payload()["rate_card"], version=version)
        assert self.errors(signer, validator, rate_card=rc)

    @pytest.mark.parametrize(
        "path,value",
        [
            (("phases", "quick"), -1),
            (("rotated_factor",), -0.1),
            (("semantic",), -0.5),
            (("device_multiplier", "gpu"), -1),
            (("model_multiplier", "advanced"), "high"),
            (("page_size", "per_page_max"), 0),
            (("pixels", "reference_megapixels"), 0),
        ],
    )
    def test_invalid_rates(self, signer, validator, path, value):
        rc = rate_payload()["rate_card"]
        node = rc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        assert self.errors(signer, validator, rate_card=rc)

    def test_more_than_three_decimal_places_rejected(self, signer, validator):
        rc = rate_payload()["rate_card"]
        rc["phases"]["moderate"] = 2.4001
        assert any("3 decimal places" in e for e in self.errors(signer, validator, rate_card=rc))

    def test_three_decimal_places_accepted(self, signer, validator):
        rc = rate_payload()["rate_card"]
        rc["phases"]["moderate"] = 2.401
        assert self.errors(signer, validator, rate_card=rc) == []

    # ---- wallets ------------------------------------------------------------------------

    def test_github_daily_split_by_visibility(self, signer, validator):
        wallets = rate_payload()["wallets"]
        assert wallets["github"] == {"daily_private": 20, "daily_public": 200}
        assert self.errors(signer, validator) == []

    @pytest.mark.parametrize(
        "wallets",
        [
            {"local": {"daily": -1}},
            {"github": {"daily_public": "many"}},
            {"addons": {"Semantic": {}}},
        ],
    )
    def test_invalid_wallets(self, signer, validator, wallets):
        assert self.errors(signer, validator, wallets=wallets)

    # ---- promotions ---------------------------------------------------------------------

    def promo(self, **over):
        base = rate_payload()["promotions"][0]
        base.update(over)
        return base

    def test_promotion_window_is_inclusive_whole_days(self, signer, validator):
        one_day = self.promo(start_date="2026-11-01", end_date="2026-11-01")
        assert self.errors(signer, validator, promotions=[one_day]) == []

    @pytest.mark.parametrize(
        "over,message",
        [
            ({"start_date": "2026-11-08", "end_date": "2026-11-07"}, "must not be after"),
            ({"start_date": "2026-02-30"}, "impossible"),
            ({"end_date": "2026-11-07T00:00:00Z"}, "UTC date"),
        ],
    )
    def test_invalid_promotion_windows(self, signer, validator, over, message):
        errs = self.errors(signer, validator, promotions=[self.promo(**over)])
        assert any(message in e or "schema" in e for e in errs), errs

    def test_duplicate_promotion_ids_rejected(self, signer, validator):
        errs = self.errors(signer, validator, promotions=[self.promo(), self.promo()])
        assert any("duplicate promotion id" in e for e in errs)

    def test_uplift_needs_exactly_one_of_absolute_or_percent(self, signer, validator):
        for uplift in ({"local": {}}, {"local": {"absolute": 5, "percent": 10}}, {}):
            assert self.errors(signer, validator, promotions=[self.promo(uplift=uplift)]), uplift

    def test_uplift_wallet_keys_checked(self, signer, validator):
        ok = {"addon:semantic": {"absolute": 5}}
        assert self.errors(signer, validator, promotions=[self.promo(uplift=ok)]) == []
        assert self.errors(
            signer, validator, promotions=[self.promo(uplift={"cloud": {"absolute": 5}})]
        )

    def test_percent_uplift_cannot_exceed_the_cap(self, signer, validator):
        caps = {"promotion_uplift_percent": 40}
        errs = self.errors(signer, validator, caps=caps)
        assert any("exceeds caps.promotion_uplift_percent" in e for e in errs)

    def test_promotion_scope_filters_accepted(self, signer, validator):
        scoped = self.promo(
            applies_to={"tiers": ["pro"], "addons": ["semantic"], "client": {"min": "1.1.0"}},
            min_client="1.1.0",
        )
        assert self.errors(signer, validator, promotions=[scoped]) == []

    # ---- grace, caps, metrics, ocr ------------------------------------------------------

    @pytest.mark.parametrize(
        "over", [{"grace_mode": "overdraft"}, {"grace_percent": -1}, {"grace_percent": 101}]
    )
    def test_invalid_grace(self, signer, validator, over):
        assert self.errors(signer, validator, **over)

    @pytest.mark.parametrize("mode", ["free", "borrow"])
    def test_grace_modes(self, signer, validator, mode):
        assert self.errors(signer, validator, grace_mode=mode) == []

    def test_metrics_bonus_defaults_to_a_cap_of_15(self, signer, validator):
        p = rate_payload()
        del p["caps"]["metrics_bonus_percent"]
        p["metrics"]["bonus_percent"] = 16
        errs = self.envelope_errors(validator, signer.sign(p))
        assert any("exceeds the metrics bonus cap 15" in e for e in errs)

    def test_metrics_bonus_follows_the_policy_cap(self, signer, validator):
        p = rate_payload()
        p["caps"]["metrics_bonus_percent"] = 20
        p["metrics"]["bonus_percent"] = 18
        assert self.envelope_errors(validator, signer.sign(p)) == []

    def test_metrics_endpoint_must_be_https(self, signer, validator):
        metrics = dict(rate_payload()["metrics"], endpoint="http://example.com/m")
        assert self.errors(signer, validator, metrics=metrics)

    def test_ocr_profile_override_values(self, signer, validator):
        assert (
            self.errors(signer, validator, ocr={"profiles": {"quick": "fast", "high": "fast"}})
            == []
        )
        assert self.errors(signer, validator, ocr={"profiles": {"quick": "ultra"}})

    def test_caps_values(self, signer, validator):
        assert self.errors(signer, validator, caps={"one_off_expiry_days": 0})
        assert self.errors(signer, validator, caps={"device_daily_ceiling": -5})


class TestRateCardExamples:
    validator = vp.PolicyValidator()

    @pytest.mark.parametrize("name", ["with-rate-card", "rate-card-scoped"])
    def test_examples_pass(self, name):
        payload = json.loads((ROOT / f"examples/v1/{name}.payload.json").read_text())
        assert self.validator.validate_payload(payload) == []

    def test_scoped_example_is_explicit_about_scope(self):
        payload = json.loads((ROOT / "examples/v1/rate-card-scoped.payload.json").read_text())
        assert payload["rate_card"]["applies_to"]["client"]["min"] == "1.2.0"


class TestKeyRevocation(ValidatorTestCase):
    """revoked_key_ids: shape and the rules the validator can check (the client does the rest)."""

    def errors(self, signer, validator, **sections):
        return self.envelope_errors(validator, signer.sign(make_payload(**sections)))

    def test_valid_list(self, signer, validator):
        assert self.errors(signer, validator, revoked_key_ids=["pol-aaaa", "lic-bbbb"]) == []

    def test_absent_and_empty_are_fine(self, signer, validator):
        assert self.errors(signer, validator) == []
        assert self.errors(signer, validator, revoked_key_ids=[]) == []

    def test_cannot_revoke_its_own_signing_key(self, signer, validator):
        errs = self.errors(signer, validator, revoked_key_ids=[KID])
        assert any("cannot revoke its own signing key" in e for e in errs)

    @pytest.mark.parametrize(
        "value", ["pol-a", [1], ["a b"], ["x"] * 2, [f"k{i}" for i in range(33)], [""]]
    )
    def test_invalid_shapes(self, signer, validator, value):
        assert self.errors(signer, validator, revoked_key_ids=value)

    def test_example_passes(self):
        payload = json.loads((ROOT / "examples/v1/with-key-revocation.payload.json").read_text())
        assert vp.PolicyValidator().validate_payload(payload) == []
        assert payload["kid"] not in payload["revoked_key_ids"]

    def test_older_validators_ignore_the_field(self, signer, validator):
        # Additive: a payload with the field is still an ordinary valid payload.
        assert self.errors(signer, validator, revoked_key_ids=["pol-aaaa"], future_field=1) == []
