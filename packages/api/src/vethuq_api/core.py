"""The one place the API talks to the VethuQ core (through its public API only)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

from vethuq_api.addons_service import AddonsService
from vethuq_api.credits_service import CreditsService
from vethuq_api.github_service import GitHubService
from vethuq_api.indexing import IndexingService
from vethuq_api.logs_service import LogsService
from vethuq_api.maintenance_service import MaintenanceService
from vethuq_api.ocr_service import OcrService
from vethuq_api.search_service import SearchService
from vethuq_api.settings import SettingsService
from vethuq_api.sources_service import SourcesService
from vethuq_api.stats_service import StatsService
from vethuq_api.support import build_report
from vethuq_api.update_install import UpdateInstaller


class Core(Protocol):
    """What the routes need from the core. Tests replace it with a fake."""

    def about(self) -> dict[str, object]: ...

    def catalog(self) -> dict[str, list[dict[str, object]]]: ...

    def brand(self) -> dict[str, object]: ...

    def settings(self, section: str) -> list[dict[str, object]]: ...

    def update_setting(
        self, section: str, setting_id: str, value: object, options: dict[str, Any] | None = None
    ) -> dict[str, object]: ...

    def reset_setting(
        self, section: str, setting_id: str, options: dict[str, Any] | None = None
    ) -> dict[str, object]: ...

    def support_report(self) -> str: ...

    def sources(self) -> Any: ...

    def indexing(self) -> Any: ...

    def credits(self) -> Any: ...

    def stats(self) -> Any: ...

    def ocr(self) -> Any: ...

    def addons(self) -> Any: ...

    def logs(self) -> Any: ...

    def github(self) -> Any: ...

    def search(self) -> Any: ...

    def maintenance(self) -> Any: ...


class VethuQCore:
    """`Core` backed by a `vethuq.VethuQ` client, created on first use."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._client: Any = None
        self._settings = SettingsService(self._vethuq, self._release)
        self._sources = SourcesService(self._vethuq)
        self._indexing = IndexingService(self._vethuq)
        self._credits = CreditsService(self._vethuq)
        self._stats = StatsService(self._vethuq)
        self._ocr = OcrService(self._vethuq)
        self._addons = AddonsService(self._vethuq)
        self._logs = LogsService(self._vethuq)
        self._github = GitHubService(self._vethuq)
        self._search = SearchService(self._vethuq)
        self._maintenance = MaintenanceService(
            self._vethuq,
            UpdateInstaller(
                self._indexing.service_probe(),
                lambda: self._indexing.service_action("stop"),
            ),
        )

    def _vethuq(self) -> Any:
        with self._lock:
            if self._client is None:
                from vethuq import VethuQ

                self._client = VethuQ(self._db_path)
            return self._client

    def _release(self) -> None:
        """Forget the client (after the data folder moved), so the next use opens the new one."""
        with self._lock:
            self._client = None
        self._sources.forget()

    def sources(self) -> SourcesService:
        return self._sources

    def indexing(self) -> IndexingService:
        return self._indexing

    def credits(self) -> CreditsService:
        return self._credits

    def stats(self) -> StatsService:
        return self._stats

    def ocr(self) -> OcrService:
        return self._ocr

    def addons(self) -> AddonsService:
        return self._addons

    def logs(self) -> LogsService:
        return self._logs

    def github(self) -> GitHubService:
        return self._github

    def search(self) -> SearchService:
        return self._search

    def maintenance(self) -> MaintenanceService:
        return self._maintenance

    def about(self) -> dict[str, object]:
        return self._vethuq().version.to_dict()

    def support_report(self) -> str:
        """Everything a support request needs, as text to paste (no folders, no file names)."""
        from vethuq import Paths

        return build_report(
            about=self.about(),
            catalog=self.catalog(),
            changed=self._settings.changed(),
            data_location=Paths.location_source(),
        )

    def settings(self, section: str) -> list[dict[str, object]]:
        return self._settings.list(section)

    def update_setting(
        self, section: str, setting_id: str, value: object, options: dict[str, Any] | None = None
    ) -> dict[str, object]:
        return self._settings.update(section, setting_id, value, options)

    def reset_setting(
        self, section: str, setting_id: str, options: dict[str, Any] | None = None
    ) -> dict[str, object]:
        return self._settings.reset(section, setting_id, options)

    def brand(self) -> dict[str, object]:
        """The app's name, tagline and colour palette, so every surface looks the same."""
        import vethuq

        # The palette is the core's shared design tokens; it has no public accessor yet, and its
        # module is documented as the thing a web layer reuses.
        from vethuq._brand import _Palette

        return {
            "name": vethuq.APP_NAME,
            "tagline": vethuq.APP_TAGLINE,
            "palette": _Palette.schemes(),
        }

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
                for item in client.file_types.list_all()
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
