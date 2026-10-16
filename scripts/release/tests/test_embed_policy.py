"""The embedding switch and the release guard."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RELEASE = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


embed = _load("embed_policy")
check = _load("check_embedded")


def _key(role: str, prefix: str = "") -> tuple[str, str]:
    raw = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    kid = f"{prefix}{role}-{hashlib.sha256(raw).hexdigest()[:16]}"
    return kid, base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _folder(tmp_path: Path, *keys: tuple[str, str]) -> Path:
    folder = tmp_path / "keys"
    folder.mkdir(exist_ok=True)
    for kid, text in keys:
        (folder / f"{kid}.pub").write_text(text + "\n")
    return folder


def _built(tmp_path, flavour, *keys) -> str:
    return embed.build(flavour, _folder(tmp_path, *keys))


class TestEmbed:
    def test_production_embeds_current_and_standby_and_the_default_urls(self, tmp_path):
        pol, pst = _key("pol"), _key("pst")

        names = check.parse(_built(tmp_path, "production", pol, pst))

        assert names["FLAVOUR"] == "production"
        assert names["POLICY_KEYS"] == {pol[0]: pol[1]}
        assert names["POLICY_STANDBY_KEYS"] == {pst[0]: pst[1]}
        assert names["POLICY_URLS"] == embed.PRODUCTION_URLS

    def test_the_generated_module_is_a_release_that_passes_the_guard(self, tmp_path):
        text = _built(tmp_path, "production", _key("pol"), _key("pst"))

        assert check.problems_in_module(text) == []

    def test_test_flavour_takes_only_test_keys_and_the_test_location(self, tmp_path):
        names = check.parse(_built(tmp_path, "test", _key("pol", "test-"), _key("pst", "test-")))

        assert names["FLAVOUR"] == "test" and names["POLICY_URLS"] == embed.TEST_URLS

    def test_a_test_key_cannot_go_into_a_production_build(self, tmp_path):
        with pytest.raises(embed.EmbedError, match="test key id"):
            _built(tmp_path, "production", _key("pol", "test-"), _key("pst"))

    def test_a_production_key_cannot_go_into_a_test_build(self, tmp_path):
        with pytest.raises(embed.EmbedError, match="unexpected key id"):
            _built(tmp_path, "test", _key("pol"), _key("pst", "test-"))

    def test_a_standby_key_is_required(self, tmp_path):
        with pytest.raises(embed.EmbedError, match="standby"):
            _built(tmp_path, "production", _key("pol"))

    def test_a_policy_key_is_required(self, tmp_path):
        with pytest.raises(embed.EmbedError, match="at least one policy key"):
            _built(tmp_path, "production", _key("pst"))

    def test_an_id_that_does_not_match_its_key_is_refused(self, tmp_path):
        kid = _key("pol")[0]
        other = _key("pol")[1]

        with pytest.raises(embed.EmbedError, match="does not match"):
            _built(tmp_path, "production", (kid, other), _key("pst"))

    def test_a_damaged_key_file_is_refused(self, tmp_path):
        kid = "pol-" + "0" * 16

        with pytest.raises(embed.EmbedError, match="32 bytes|base64url"):
            _built(tmp_path, "production", (kid, "AAAA"), _key("pst"))

    def test_an_empty_folder_is_refused(self, tmp_path):
        (tmp_path / "keys").mkdir()
        with pytest.raises(embed.EmbedError, match="no .pub"):
            embed.build("production", tmp_path / "keys")

    def test_development_embeds_nothing_and_takes_no_keys(self, tmp_path):
        names = check.parse(embed.build("development", None))

        assert names["POLICY_KEYS"] == {} and names["POLICY_URLS"] == ()
        with pytest.raises(embed.EmbedError):
            embed.build("development", tmp_path)

    def test_the_cli_writes_the_file(self, tmp_path):
        out = tmp_path / "embedded.py"
        folder = _folder(tmp_path, _key("pol"), _key("pst"))

        assert (
            embed.main(["--flavour", "production", "--keys-dir", str(folder), "--out", str(out)])
            == 0
        )
        assert check.problems_in_module(out.read_text()) == []
        assert embed.main(["--flavour", "production", "--out", str(out)]) == 1


class TestGuard:
    def test_the_committed_development_module_is_not_a_release(self):
        found = check.problems_in_module(embed.build("development", None))

        assert any("flavour" in p for p in found) and any("standby" in p for p in found)

    def test_a_test_build_is_not_a_release(self, tmp_path):
        found = check.problems_in_module(
            _built(tmp_path, "test", _key("pol", "test-"), _key("pst", "test-"))
        )

        assert any("flavour" in p for p in found)
        assert any("test-pol-" in p or "not a production key id" in p for p in found)
        assert any("not a production https location" in p for p in found)

    def test_a_release_without_a_standby_key_fails(self):
        pol = _key("pol")
        text = embed.render("production", {pol[0]: pol[1]}, {})

        assert any("no standby key" in p for p in check.problems_in_module(text))

    def test_a_test_url_fails_even_with_production_keys(self):
        pol, pst = _key("pol"), _key("pst")
        text = embed.render("production", {pol[0]: pol[1]}, {pst[0]: pst[1]}).replace(
            "/policy/v1/", "/policy/test/v1/"
        )

        assert any("production https location" in p for p in check.problems_in_module(text))

    def test_a_key_in_the_wrong_group_fails(self):
        pol, pst = _key("pol"), _key("pst")
        text = embed.render("production", {pst[0]: pst[1]}, {pol[0]: pol[1]})

        found = check.problems_in_module(text)
        assert any("not a pol- key" in p for p in found) and any(
            "not a pst- key" in p for p in found
        )

    def test_an_unreadable_module_fails(self):
        (problem,) = check.problems_in_module("FLAVOUR = (")

        assert "cannot be read" in problem


def _wheel(tmp_path: Path, embedded: str, **other: str) -> Path:
    path = tmp_path / "vethuq-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(check.EMBEDDED, embedded)
        for name, text in other.items():
            wheel.writestr(name, text)
    return path


class TestWheel:
    @pytest.fixture
    def release(self, tmp_path):
        return embed.build("production", _folder(tmp_path, _key("pol"), _key("pst")))

    def test_a_clean_release_wheel_passes(self, tmp_path, release):
        assert check.check_wheel(_wheel(tmp_path, release, **{"vethuq/a.py": "x = 1"})) == []

    def test_a_test_key_anywhere_in_the_wheel_fails(self, tmp_path, release):
        wheel = _wheel(tmp_path, release, **{"vethuq/oops.py": 'KEY = "test-pol-7ae87a37d5a9a4ff"'})

        assert any("test key id test-pol-7ae87a37d5a9a4ff" in p for p in check.check_wheel(wheel))

    def test_a_wheel_without_the_module_fails(self, tmp_path):
        path = tmp_path / "x.whl"
        with zipfile.ZipFile(path, "w") as wheel:
            wheel.writestr("vethuq/a.py", "")

        assert any("missing" in p for p in check.check_wheel(path))

    def test_the_cli_exit_codes(self, tmp_path, release):
        good, bad = _wheel(tmp_path, release), tmp_path / "bad"
        bad.mkdir()
        worse = _wheel(bad, embed.build("development", None))

        assert check.main(["--wheel", str(good)]) == 0
        assert check.main(["--wheel", str(worse)]) == 1
        module = tmp_path / "m.py"
        module.write_text(release)
        assert check.main(["--module", str(module)]) == 0
        module.write_text(embed.build("development", None))
        assert check.main(["--module", str(module)]) == 1
