"""Finding, downloading and removing the OCR models.

PaddleX keeps each model in its own folder under `<cache>/official_models/<name>`, where `<cache>`
is `$PADDLE_PDX_CACHE_HOME` or `~/.paddlex`, and downloads one the first time OCR asks for it. This
module works on those folders without importing PaddleX (the desktop UI and CLI do not ship it),
and downloads in a child process: the worker executable in the desktop build, `python -m` otherwise.

The cache is shared with anything else on the machine that uses PaddleX, so only the models named
in the manifests are ever removed - see `OcrModels.clean`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vethuq_core.logs import Logs
from vethuq_core.ocr.catalog import OcrCatalog, OcrComponentInfo

_logger = Logs.get_logger("index")


@dataclass(frozen=True)
class ModelStatus:
    """One model: its folder, whether it is downloaded and which languages need it
    (every language, for a model they share)."""

    name: str
    path: Path
    present: bool
    size_bytes: int
    languages: tuple[str, ...]
    shared: bool


@dataclass
class DownloadResult:
    downloaded: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass
class ClearResult:
    removed: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    kept_shared: list[str] = field(default_factory=list)


@dataclass
class CleanResult:
    removed: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    unmanaged: list[str] = field(default_factory=list)


class OcrModels:
    # The engine whose models these are; there is only one today (see `Engines.DEFAULT`).
    ENGINE = "paddle"
    WORKER_FLAG = "--fetch-models"
    _WORKER_EXE_NAME = "vethuq-worker.exe"

    @staticmethod
    def cache_dir() -> Path:
        """The folder the OCR models are kept in (PaddleX's own cache, so a model downloaded
        by either is found by both)."""
        home = os.environ.get("PADDLE_PDX_CACHE_HOME")
        root = Path(home) if home else Path.home() / ".paddlex"
        return root / "official_models"

    @staticmethod
    def _engine() -> OcrComponentInfo | None:
        return next((e for e in OcrCatalog.engines() if e.id == OcrModels.ENGINE), None)

    @staticmethod
    def shared() -> tuple[str, ...]:
        """The models every language uses (text detection and orientation)."""
        engine = OcrModels._engine()
        return engine.models if engine is not None else ()

    @staticmethod
    def own(language_id: str) -> tuple[str, ...]:
        """The models only `language_id` uses (its recognizer)."""
        language = OcrCatalog.language(language_id)
        return language.models_for(OcrModels.ENGINE) if language is not None else ()

    @staticmethod
    def required(language_id: str) -> list[str]:
        """Every model OCR in `language_id` needs, shared ones first."""
        return [*OcrModels.shared(), *OcrModels.own(language_id)]

    @staticmethod
    def managed() -> dict[str, tuple[str, ...]]:
        """Every model VethuQ knows, by name, with the languages that need it."""
        everyone = tuple(lang.id for lang in OcrCatalog.languages())
        known: dict[str, tuple[str, ...]] = dict.fromkeys(OcrModels.shared(), everyone)
        for language in OcrCatalog.languages():
            for name in OcrModels.own(language.id):
                known[name] = (*known.get(name, ()), language.id)
        return known

    @staticmethod
    def _folder(name: str) -> Path:
        return OcrModels.cache_dir() / name

    @staticmethod
    def _size(folder: Path) -> int:
        return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())

    @staticmethod
    def is_present(name: str) -> bool:
        """Whether a model's folder exists and holds something (PaddleX itself trusts any
        existing folder, so a half-finished download shows up as missing only if empty)."""
        folder = OcrModels._folder(name)
        return folder.is_dir() and any(folder.iterdir())

    @staticmethod
    def status(language_ids: list[str] | None = None) -> list[ModelStatus]:
        """The models `language_ids` need (default: every known language), shared ones first."""
        ids = (
            language_ids
            if language_ids is not None
            else [lang.id for lang in OcrCatalog.languages()]
        )
        known = OcrModels.managed()
        shared = set(OcrModels.shared())
        names = list(
            dict.fromkeys(
                [name for lang in ids for name in OcrModels.required(lang) if name in shared]
                + [name for lang in ids for name in OcrModels.required(lang)]
            )
        )
        result = []
        for name in names:
            folder = OcrModels._folder(name)
            present = OcrModels.is_present(name)
            result.append(
                ModelStatus(
                    name=name,
                    path=folder,
                    present=present,
                    size_bytes=OcrModels._size(folder) if present else 0,
                    languages=known.get(name, ()),
                    shared=name in shared,
                )
            )
        return result

    @staticmethod
    def missing(language_id: str) -> list[str]:
        """The models OCR in `language_id` still needs downloaded."""
        return [name for name in OcrModels.required(language_id) if not OcrModels.is_present(name)]

    @staticmethod
    def is_ready(language_id: str) -> bool:
        return not OcrModels.missing(language_id)

    # -- removing ---------------------------------------------------------------------------

    @staticmethod
    def _remove(name: str) -> int:
        folder = OcrModels._folder(name)
        size = OcrModels._size(folder) if folder.is_dir() else 0
        shutil.rmtree(folder, ignore_errors=False)
        return size

    @staticmethod
    def clear(language_ids: list[str], *, include_shared: bool = False) -> ClearResult:
        """Delete the downloaded models of `language_ids`.

        A language's own recognizer goes. The models every language shares stay unless
        `include_shared`, because the other languages still read with them; they are reported in
        `kept_shared`. Nothing but VethuQ's own models is touched.
        """
        result = ClearResult()
        names = list(dict.fromkeys(name for lang in language_ids for name in OcrModels.own(lang)))
        for name in names:
            if OcrModels.is_present(name) or OcrModels._folder(name).exists():
                OcrModels._remove(name)
                result.removed.append(name)
            else:
                result.absent.append(name)
        for name in OcrModels.shared():
            if include_shared and OcrModels._folder(name).exists():
                OcrModels._remove(name)
                result.removed.append(name)
            elif not include_shared and OcrModels.is_present(name):
                result.kept_shared.append(name)
        _logger.info(
            "Cleared OCR models for %s: removed %s",
            ",".join(language_ids) or "-",
            ",".join(result.removed) or "none",
        )
        return result

    @staticmethod
    def clean(enabled_language_ids: list[str]) -> CleanResult:
        """Remove what is not in use: models of languages that are not enabled, and empty or
        leftover download folders.

        Shared models stay while any language is enabled. Folders in the cache that are not
        VethuQ's models belong to something else using PaddleX and are left alone (listed in
        `unmanaged`).
        """
        result = CleanResult()
        cache = OcrModels.cache_dir()
        if not cache.is_dir():
            return result
        needed = {name for lang in enabled_language_ids for name in OcrModels.required(lang)}
        known = OcrModels.managed()
        for folder in sorted(p for p in cache.iterdir() if p.is_dir()):
            name = folder.name
            if name in known:
                empty = not any(folder.iterdir())
                if empty or name not in needed:
                    result.bytes_freed += OcrModels._size(folder)
                    shutil.rmtree(folder)
                    result.removed.append(name)
            else:
                result.unmanaged.append(name)
        _logger.info(
            "Cleaned OCR models: removed %s, left %d unmanaged",
            ",".join(result.removed) or "none",
            len(result.unmanaged),
        )
        return result

    # -- downloading ------------------------------------------------------------------------

    @staticmethod
    def _fetch_command(names: list[str]) -> list[str]:
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name(OcrModels._WORKER_EXE_NAME)
            if not worker.exists():
                raise FileNotFoundError(f"OCR worker not found at {worker}")
            return [str(worker), OcrModels.WORKER_FLAG, *names]
        return [sys.executable, "-m", "vethuq_core.ocr.models.fetch", *names]

    @staticmethod
    def _run_fetch(names: list[str], on_event: Callable[[dict], None]) -> int:
        """Run the download child process, calling `on_event` with each status line it prints."""
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            OcrModels._fetch_command(names),
            env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        assert process.stdout is not None
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                on_event(event)
        return process.wait()

    @staticmethod
    def download(
        language_ids: list[str],
        *,
        force: bool = False,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> DownloadResult:
        """Download the models `language_ids` need that are not on disk (all of them with
        `force`). `on_progress(model, state)` is called with state `downloading`, `ready` or
        `failed`."""
        result = DownloadResult()
        wanted = list(
            dict.fromkeys(name for lang in language_ids for name in OcrModels.required(lang))
        )
        todo = [name for name in wanted if force or not OcrModels.is_present(name)]
        result.already_present = [name for name in wanted if name not in todo]
        if not todo:
            return result
        if force:
            for name in todo:
                if OcrModels._folder(name).exists():
                    OcrModels._remove(name)

        reported: set[str] = set()

        def handle(event: dict) -> None:
            name, state = str(event.get("model", "")), str(event.get("status", ""))
            if name not in todo:
                return
            if on_progress is not None:
                on_progress(name, state)
            if state == "ready" and name not in result.downloaded:
                result.downloaded.append(name)
            elif state == "failed":
                result.failed[name] = str(event.get("error", "unknown error"))
            reported.add(name)

        try:
            code = OcrModels._run_fetch(todo, handle)
        except (OSError, FileNotFoundError) as exc:
            for name in todo:
                result.failed[name] = str(exc)
            _logger.error("Could not start the OCR model download: %s", exc)
            return result
        for name in todo:
            if name not in result.downloaded and name not in result.failed:
                result.failed[name] = f"the download ended without a result (exit code {code})"
        _logger.info(
            "OCR model download: %d downloaded, %d failed",
            len(result.downloaded),
            len(result.failed),
        )
        return result
