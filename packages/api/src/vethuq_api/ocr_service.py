"""OCR for the interface: the engines and phases installed, and the model files on disk."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from vethuq_api.indexing import IndexingRefusedError


class OcrService:
    """Reads the core's OCR and runs the slow part, downloading models, on a thread so the
    interface can show it go. One job at a time; the rest (listing, removing) answers at once."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._job: dict[str, Any] = {
            "running": False,
            "action": None,
            "progress": {},
            "error": None,
            "finished": False,
        }

    # ----- what is installed ------------------------------------------------------------------

    def engines(self) -> list[dict[str, object]]:
        return [e.to_dict() for e in self._client().ocr.engines.list()]

    def phases(self) -> list[dict[str, object]]:
        return [
            p.to_dict() for p in sorted(self._client().ocr.phases.list(), key=lambda p: p.order)
        ]

    def models(self, languages: list[str] | None = None) -> dict[str, object]:
        models = self._client().ocr.models
        rows = [m.to_dict() for m in models.list(languages or None)]
        return {
            "folder": str(models.cache_dir),
            "items": rows,
            "installed": sum(1 for r in rows if r["installed"]),
            "size_bytes": sum(int(r["size_bytes"]) for r in rows),
        }

    # ----- the download job -------------------------------------------------------------------

    def job(self) -> dict[str, object]:
        with self._lock:
            return {**self._job, "progress": dict(self._job["progress"])}

    def start(
        self,
        action: str,
        languages: list[str] | None = None,
        names: list[str] | None = None,
    ) -> dict[str, object]:
        """Download missing models (`download`) or delete and fetch them again (`redownload`)."""
        if action not in ("download", "redownload"):
            raise ValueError("action is download or redownload.")
        with self._lock:
            if self._job["running"]:
                raise IndexingRefusedError("Models are being downloaded already.", 409)
            self._job = {
                "running": True,
                "action": action,
                "progress": {},
                "error": None,
                "finished": False,
            }
        threading.Thread(
            target=self._run, args=(action, languages or None, names or None), daemon=True
        ).start()
        return self.job()

    def _note(self, name: str, state: str) -> None:
        with self._lock:
            self._job["progress"][name] = state

    def _run(self, action: str, languages: list[str] | None, names: list[str] | None) -> None:
        error = None
        try:
            models = self._client().ocr.models
            if action == "download":
                models.download(languages, self._note)
            else:
                models.redownload(names, languages)
        except Exception as failure:  # noqa: BLE001 - the interface shows why it failed
            error = str(failure)
        with self._lock:
            self._job.update(running=False, finished=True, error=error)

    # ----- removing ---------------------------------------------------------------------------

    def clear(self, languages: list[str], include_shared: bool) -> list[str]:
        if not languages:
            raise ValueError("Pick a language to remove its models.")
        self._refuse_while_running()
        return self._client().ocr.models.clear(languages, include_shared=include_shared)

    def clean(self) -> list[str]:
        self._refuse_while_running()
        return self._client().ocr.models.clean()

    def _refuse_while_running(self) -> None:
        if self.job()["running"]:
            raise IndexingRefusedError("Models are being downloaded. Wait for that to finish.", 409)
