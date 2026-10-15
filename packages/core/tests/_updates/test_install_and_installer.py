from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from tests.policy_factory import PolicySigner
from vethuq._policy import Policy
from vethuq._updates import InstallerDownload, InstallerError, InstallKind, _Install, _Installer


class TestInstallKind:
    def test_a_frozen_build_is_the_installer(self):
        assert _Install.kind(frozen=True) is InstallKind.INSTALLER

    def test_a_virtual_environment(self):
        assert (
            _Install.kind(frozen=False, prefix="/p/.venv", base_prefix="/usr") is InstallKind.VENV
        )

    def test_pipx_is_a_virtual_environment_under_pipx(self):
        kind = _Install.kind(
            frozen=False, prefix="/home/u/.local/pipx/venvs/vethuq", base_prefix="/usr"
        )
        assert kind is InstallKind.PIPX

    def test_an_externally_managed_python(self, tmp_path):
        (tmp_path / "EXTERNALLY-MANAGED").write_text("[externally-managed]")
        kind = _Install.kind(frozen=False, prefix="/usr", base_prefix="/usr", stdlib=str(tmp_path))
        assert kind is InstallKind.EXTERNALLY_MANAGED

    def test_plain_pip(self, tmp_path):
        kind = _Install.kind(frozen=False, prefix="/usr", base_prefix="/usr", stdlib=str(tmp_path))
        assert kind is InstallKind.PIP


class TestUpgradeHelp:
    def test_pip_and_venv_give_the_pip_command(self):
        for kind in (InstallKind.PIP, InstallKind.VENV):
            help_ = _Install.help(kind)
            assert "-m pip install --upgrade vethuq" in help_.commands[0]

    def test_addons_are_included(self):
        help_ = _Install.help(
            InstallKind.VENV, ["vethuq-addon-pdf", "vethuq-addon-pdf", "vethuq-addon-ocr"]
        )
        assert help_.commands[0].endswith("vethuq vethuq-addon-pdf vethuq-addon-ocr")
        assert help_.addons == ("vethuq-addon-pdf", "vethuq-addon-ocr")

    def test_pipx_upgrades_and_reinjects_addons(self):
        help_ = _Install.help(InstallKind.PIPX, ["vethuq-addon-pdf"])
        assert help_.commands == (
            "pipx upgrade vethuq",
            "pipx inject --force vethuq vethuq-addon-pdf",
        )

    def test_an_externally_managed_python_is_not_told_to_use_pip_on_it(self):
        help_ = _Install.help(InstallKind.EXTERNALLY_MANAGED)
        assert "PEP 668" in help_.steps[0]
        assert all("sudo" not in c and "--break-system-packages" not in c for c in help_.commands)
        assert help_.commands[0].startswith("python3 -m venv")

    def test_the_installer_install_has_no_shell_command(self):
        help_ = _Install.help(InstallKind.INSTALLER)
        assert help_.commands == () and "Install now" in help_.steps[0]

    def test_to_dict(self):
        assert _Install.help(InstallKind.PIPX).to_dict()["install_type"] == "pipx"


def _policy(downloads):
    versions = {
        "desktop": {"latest": "2.0.0", "minimum_supported": "1.0.0", "downloads": downloads}
    }
    return Policy.from_payload(PolicySigner().payload(versions=versions))


GOOD = b"installer-bytes"
DIGEST = hashlib.sha256(GOOD).hexdigest()


def _entry(**over):
    item = {
        "platform": "windows-x64",
        "url": "https://dl.test/Setup.exe",
        "size": len(GOOD),
        "sha256": DIGEST,
    }
    return {**item, **over}


class TestInstallerEntry:
    def test_finds_the_entry_for_the_platform(self):
        entry = _Installer.entry(
            _policy([_entry(), _entry(platform="linux-x64")]), platform="windows-x64"
        )
        assert entry == InstallerDownload(
            "windows-x64", "https://dl.test/Setup.exe", len(GOOD), DIGEST
        )

    @pytest.mark.parametrize(
        "bad",
        [
            {"url": "http://dl.test/Setup.exe"},
            {"sha256": DIGEST.upper()},
            {"sha256": "abc"},
            {"size": 0},
            {"size": "9"},
            {"url": 5},
        ],
    )
    def test_a_malformed_entry_is_not_used(self, bad):
        assert _Installer.entry(_policy([_entry(**bad)]), platform="windows-x64") is None

    def test_no_downloads_or_no_matching_platform(self):
        assert _Installer.entry(_policy([]), platform="windows-x64") is None
        assert _Installer.entry(_policy([_entry()]), platform="macos-arm64") is None

    def test_the_platform_key_looks_like_the_policys(self):
        assert _Installer.platform_key().split("-")[0] in {"windows", "macos", "linux"}


class _Response(io.BytesIO):
    def __init__(self, body, url="https://dl.test/Setup.exe"):
        super().__init__(body)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _opener(body, url="https://dl.test/Setup.exe"):
    return lambda request, timeout=None: _Response(body, url)


def _download(entry="x", **over):
    return InstallerDownload(
        "windows-x64",
        "https://dl.test/Setup.exe",
        over.get("size", len(GOOD)),
        over.get("sha256", DIGEST),
    )


class TestInstallerFetch:
    def test_a_matching_file_is_returned(self, tmp_path):
        path = _Installer.fetch(_download(), tmp_path, opener=_opener(GOOD))

        assert path == tmp_path / "Setup.exe" and path.read_bytes() == GOOD
        assert not list(tmp_path.glob("*.part"))

    def test_a_wrong_hash_is_deleted_and_refused(self, tmp_path):
        with pytest.raises(InstallerError, match="checksum"):
            _Installer.fetch(_download(sha256="0" * 64), tmp_path, opener=_opener(GOOD))

        assert list(tmp_path.iterdir()) == []

    def test_too_large_and_too_small_are_refused(self, tmp_path):
        with pytest.raises(InstallerError, match="larger"):
            _Installer.fetch(_download(size=3), tmp_path, opener=_opener(GOOD))
        with pytest.raises(InstallerError, match="smaller"):
            _Installer.fetch(_download(size=len(GOOD) + 1), tmp_path, opener=_opener(GOOD))
        assert list(tmp_path.iterdir()) == []

    def test_an_insecure_address_or_redirect_is_refused(self, tmp_path):
        insecure = InstallerDownload("p", "http://dl.test/Setup.exe", len(GOOD), DIGEST)
        with pytest.raises(InstallerError, match="secure"):
            _Installer.fetch(insecure, tmp_path, opener=_opener(GOOD))
        with pytest.raises(InstallerError, match="redirected"):
            _Installer.fetch(_download(), tmp_path, opener=_opener(GOOD, "http://evil.test/x"))

    def test_a_network_failure_is_an_installer_error(self, tmp_path):
        def failing(request, timeout=None):
            raise OSError("connection reset")

        with pytest.raises(InstallerError, match="connection reset"):
            _Installer.fetch(_download(), Path(tmp_path), opener=failing)
