"""Add-ons for the interface: what is installed, what could be, and installing and updating.

Installing runs `pip` in the environment VethuQ runs in. Only packs that VethuQ itself names as
extras, and updates the signed policy announces for an installed add-on, can be asked for: the
interface never passes a name it was given to pip.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from vethuq_api.indexing import IndexingRefusedError

PIP_TIMEOUT_SECONDS = 20 * 60
LOG_LINES = 200

# What each pack adds, in words (VethuQ names the packs, not what they do).
PACK_NOTES = {
    "images": (
        "Read image files (PNG, JPG, TIFF, BMP, GIF, WebP, JPEG 2000) and the pictures Markdown "
        "files link to."
    ),
    "deep-scan": "The deeper OCR phases, moderate and deep.",
    "search": "Every search engine and normalizer.",
    "lexical": "The lexical search engine.",
    "proximity": "Find words near each other.",
    "fuzzy": "Find similar words (misspellings, OCR misreads).",
    "noise-fuzzy": "Similar words, tolerant of noise and look-alike characters.",
    "semantic": "Search by meaning. Preparing pages costs credits.",
    "github": "Run OCR in your own GitHub account.",
    "web": "HTML, XML, CSS, JavaScript and JSON files (licensed).",
    "developer": "YAML and JSON files (licensed).",
    "data": "CSV, TSV, Parquet, JSON and NDJSON files (Parquet, JSON and NDJSON licensed).",
    "office": "Word, Excel, PowerPoint, RTF and email files (licensed).",
}

Runner = Callable[[list[str]], tuple[int, list[str]]]


def run_pip(args: list[str]) -> tuple[int, list[str]]:
    """Run pip with this Python, and give back its exit code and the end of its output."""
    done = subprocess.run(  # noqa: S603 - the arguments come from VethuQ's own lists
        [sys.executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT_SECONDS,
        check=False,
    )
    lines = (done.stdout + done.stderr).splitlines()
    return done.returncode, lines[-LOG_LINES:]


def _version(text: str | None) -> Version | None:
    try:
        return Version(text) if text else None
    except InvalidVersion:
        return None


class AddonsService:
    """Reads the core's add-ons; installs and updates them on a thread, one job at a time."""

    def __init__(
        self,
        client: Callable[[], Any],
        runner: Runner = run_pip,
        frozen: bool | None = None,
    ) -> None:
        self._client = client
        self._runner = runner
        self._frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self._lock = threading.Lock()
        self._job = self._idle()

    @staticmethod
    def _idle() -> dict[str, Any]:
        return {
            "running": False,
            "action": None,
            "target": None,
            "log": [],
            "error": None,
            "finished": False,
        }

    # ----- what is installed ------------------------------------------------------------------

    def installed(self) -> list[dict[str, object]]:
        client = self._client()
        policy = client.policy.current().policy.addons
        rows = []
        for info in client.addons.list():
            rule = policy.get(info.id)
            latest = rule.latest if rule else None
            newer = _version(latest) is not None and (
                _version(info.version) is None or _version(latest) > _version(info.version)
            )
            package_known = self._distribution(info.name) is not None
            rows.append(
                {
                    **info.to_dict(),
                    "licence": bool(client.addons.settings(info.id).get("licence")),
                    "switched_off": rule is not None and not rule.enabled,
                    "message": rule.message if rule else None,
                    "latest": latest,
                    "update": bool(newer and package_known),
                    # A change made here that the running process has not picked up yet.
                    "restart": info.disabled != (info.status.value == "disabled"),
                }
            )
        return rows

    @staticmethod
    def _distribution(name: str) -> metadata.Distribution | None:
        try:
            return metadata.distribution(name)
        except metadata.PackageNotFoundError:
            return None

    def packs(self) -> list[dict[str, object]]:
        """The optional packs VethuQ names (its extras), and whether each is installed."""
        found: dict[str, list[Requirement]] = {}
        for text in metadata.requires("vethuq") or []:
            requirement = Requirement(text)
            if requirement.marker is None:
                continue
            for extra in PACK_NOTES.keys() | self._extras():
                if requirement.marker.evaluate(
                    {"extra": extra}
                ) and not requirement.marker.evaluate({"extra": ""}):
                    found.setdefault(extra, []).append(requirement)
        packs = []
        for extra, requirements in sorted(found.items()):
            versions = {r.name: self._installed_version(r.name) for r in requirements}
            packs.append(
                {
                    "id": extra,
                    "note": PACK_NOTES.get(extra, ""),
                    "packages": [
                        {"name": name, "version": version} for name, version in versions.items()
                    ],
                    "installed": all(v is not None for v in versions.values()),
                }
            )
        return packs

    @staticmethod
    def _extras() -> set[str]:
        return set(metadata.metadata("vethuq").get_all("Provides-Extra") or [])

    @staticmethod
    def _installed_version(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    def can_install(self) -> dict[str, object]:
        """Whether this installation of VethuQ can add packages, and if not why."""
        if self._frozen:
            return {
                "ok": False,
                "reason": "This copy of VethuQ is packaged and can't add packages.",
            }
        return {"ok": True, "reason": ""}

    # ----- turning one off --------------------------------------------------------------------

    def set_enabled(self, addon_id: str, enabled: bool) -> dict[str, object]:
        return self._client().addons.set_enabled(addon_id, enabled).to_dict()

    # ----- installing and updating ------------------------------------------------------------

    def job(self) -> dict[str, object]:
        with self._lock:
            return {**self._job, "log": list(self._job["log"])}

    def install(self, pack: str) -> dict[str, object]:
        match = next((p for p in self.packs() if p["id"] == pack), None)
        if match is None:
            raise ValueError(f"VethuQ has no pack called {pack!r}.")
        names = [str(p["name"]) for p in match["packages"]]  # type: ignore[union-attr]
        # Name and version range only: the marker that ties it to the pack is not for pip.
        requirements = [
            f"{r.name}{r.specifier}"
            for text in metadata.requires("vethuq") or []
            for r in [Requirement(text)]
            if r.marker is not None and r.marker.evaluate({"extra": pack}) and r.name in names
        ]
        return self._start("install", pack, requirements)

    def update(self, addon_id: str) -> dict[str, object]:
        row = next((r for r in self.installed() if r["id"] == addon_id), None)
        if row is None or not row["update"]:
            raise ValueError(f"No update is announced for {addon_id!r}.")
        return self._start("update", addon_id, [str(row["name"])], upgrade=True)

    def _start(
        self, action: str, target: str, requirements: list[str], upgrade: bool = False
    ) -> dict[str, object]:
        problem = self.can_install()
        if not problem["ok"]:
            raise IndexingRefusedError(str(problem["reason"]), 409)
        with self._lock:
            if self._job["running"]:
                raise IndexingRefusedError("Something is being installed already.", 409)
            self._job = {**self._idle(), "running": True, "action": action, "target": target}
            started = {**self._job, "log": []}
        args = [
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *(["--upgrade"] if upgrade else []),
            *requirements,
        ]
        threading.Thread(target=self._run, args=(args,), daemon=True).start()
        return started

    def _run(self, args: list[str]) -> None:
        error = None
        log: list[str] = []
        try:
            code, log = self._runner(args)
            if code != 0:
                error = "pip could not finish. The last lines of its output are below."
            else:
                importlib.invalidate_caches()
                self._client().addons.reload()
        except Exception as failure:  # noqa: BLE001 - shown to the person who asked
            error = str(failure)
        with self._lock:
            self._job.update(running=False, finished=True, error=error, log=log[-LOG_LINES:])
