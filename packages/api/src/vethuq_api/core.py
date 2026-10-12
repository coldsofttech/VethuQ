"""The one place the API talks to the VethuQ core (through its public API only)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol


class Core(Protocol):
    """What the routes need from the core. Tests replace it with a fake."""

    def about(self) -> dict[str, object]: ...

    def catalog(self) -> dict[str, list[dict[str, object]]]: ...


class VethuQCore:
    """`Core` backed by a `vethuq.VethuQ` client, created on first use."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._client: Any = None

    def _vethuq(self) -> Any:
        with self._lock:
            if self._client is None:
                from vethuq import VethuQ

                self._client = VethuQ(self._db_path)
            return self._client

    def about(self) -> dict[str, object]:
        return self._vethuq().version.to_dict()

    def catalog(self) -> dict[str, list[dict[str, object]]]:
        """What is installed and what each piece offers (what the CLI lists with `... list`)."""
        client = self._vethuq()
        return {
            "add_ons": [
                {
                    "id": item.id,
                    "name": item.name,
                    "version": item.version,
                    "status": getattr(item.status, "value", str(item.status)),
                    "detail": item.detail,
                }
                for item in client.addons.list()
            ],
            "file_types": [
                {
                    "id": item.id,
                    "label": item.label,
                    "extensions": list(item.extensions),
                    "available": item.available,
                    "reason": item.reason,
                }
                for item in client.file_types.list()
            ],
            "search_engines": [
                {
                    "id": item.id,
                    "label": item.label,
                    "description": item.description,
                    "available": item.available,
                    "reason": item.reason,
                }
                for item in client.search.engines()
            ],
            "languages": [
                {
                    "id": item.id,
                    "label": item.label,
                    "native_label": item.native_label,
                    "enabled": item.enabled,
                    "available": item.available,
                    "reason": item.reason,
                }
                for item in client.languages.list_all()
            ],
            "ocr_engines": [
                {
                    "id": item.id,
                    "label": item.label,
                    "profiles": list(item.profiles),
                    "available": item.available,
                    "reason": item.reason,
                }
                for item in client.ocr.engines.list()
            ],
        }
