"""Maintenance for the interface: the database check, updates, the signed policy, the search
index and the processing tiers. The slow ones (checking the database, rebuilding the search
index) run as tasks on a thread, one of each kind at a time."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from vethuq_api.indexing import IndexingRefusedError

TASKS = ("db-check", "search-rebuild", "update-install")


class MaintenanceService:
    def __init__(self, client: Callable[[], Any], installer: Any = None) -> None:
        self._client = client
        self._installer = installer
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {
            name: {"running": False, "result": None, "error": None, "finished": False}
            for name in TASKS
        }

    # ----- tasks ------------------------------------------------------------------------------

    def tasks(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: dict(state) for name, state in self._tasks.items()}

    def _start(self, name: str, work: Callable[[], Any]) -> dict[str, Any]:
        with self._lock:
            if self._tasks[name]["running"]:
                raise IndexingRefusedError("That is already running.", 409)
            self._tasks[name] = {"running": True, "result": None, "error": None, "finished": False}
            started = dict(self._tasks[name])

        def run() -> None:
            result, error = None, None
            try:
                result = work()
            except Exception as failure:  # noqa: BLE001 - shown to the person who asked
                error = str(failure)
            with self._lock:
                self._tasks[name] = {
                    "running": False,
                    "result": result,
                    "error": error,
                    "finished": True,
                }

        threading.Thread(target=run, daemon=True).start()
        return started

    # ----- the database -----------------------------------------------------------------------

    def db_status(self) -> dict[str, object]:
        result = self._client().db.integrity_status()
        return {"last": result.to_dict() if result is not None else None}

    def db_check(self, quick: bool) -> dict[str, Any]:
        db = self._client().db
        return self._start("db-check", lambda: db.integrity_check(quick=quick).to_dict())

    # ----- updates ----------------------------------------------------------------------------

    def updates(self) -> dict[str, object]:
        return self._client().updates.status().to_dict()

    def updates_check(self, force: bool) -> dict[str, object]:
        return self._client().updates.check(force).to_dict()

    def update_later(self, days: float) -> dict[str, object]:
        """Hide the update notice for `days` days."""
        self._client().settings.updates.snooze(days)
        return self._client().updates.status().to_dict()

    def update_skip(self) -> dict[str, object]:
        """Stop announcing the version that is on offer now (a newer one is announced again)."""
        client = self._client()
        latest = client.updates.status().latest
        if not latest:
            raise IndexingRefusedError("There is no update to skip.", 409)
        client.settings.updates.skip_version(latest)
        return client.updates.status().to_dict()

    def update_help(self) -> dict[str, object]:
        """The install type and the steps that upgrade it, for installs the dialog can't do."""
        client = self._client()
        return {**client.updates.status().to_dict(), **client.updates.upgrade_help().to_dict()}

    def update_install(self) -> dict[str, Any]:
        """Install now, as a task. The answer to the request is that it started."""
        if self._installer is None:
            raise IndexingRefusedError("Installing from here is not available.", 422)
        installer = self._installer
        client = self._client()
        installer.plan(client)  # refuse now, in words, rather than inside the task
        return self._start("update-install", lambda: installer.install(client))

    # ----- the signed policy ------------------------------------------------------------------

    @staticmethod
    def _policy(result: Any) -> dict[str, object]:
        policy = result.policy
        return {
            **result.to_dict(),
            "schema_version": policy.schema_version,
            "issued_at": policy.issued_at.isoformat() if policy.issued_at else None,
            "versions": {
                name: {
                    "latest": v.latest,
                    "minimum_supported": v.minimum_supported,
                    "release_notes_url": v.release_notes_url,
                }
                for name, v in policy.versions.items()
            },
            "notices": [
                {"id": n.id, "message": n.message, "severity": n.severity, "link": n.link}
                for n in policy.notices
            ],
            "features": {
                name: {"enabled": f.enabled, "min_client": f.min_client, "message": f.message}
                for name, f in policy.features.items()
            },
            "addons": {
                name: {
                    "enabled": a.enabled,
                    "latest": a.latest,
                    "minimum_supported": a.minimum_supported,
                    "message": a.message,
                }
                for name, a in policy.addons.items()
            },
        }

    def policy(self) -> dict[str, object]:
        return self._policy(self._client().policy.current())

    def policy_refresh(self, force: bool) -> dict[str, object]:
        return self._policy(self._client().policy.refresh(force))

    # ----- the search index -------------------------------------------------------------------

    def search_index(self) -> dict[str, object]:
        return self._client().search.status().to_dict()

    def search_rebuild(self) -> dict[str, Any]:
        search = self._client().search

        def work() -> dict[str, object]:
            result = search.rebuild()
            if not result.ok:
                raise RuntimeError(f"The search index could not be rebuilt: {result.error}")
            return {"pages": result.pages, "seconds": round(result.seconds, 2)}

        return self._start("search-rebuild", work)

    # ----- shared usage metrics ---------------------------------------------------------------

    def metrics(self) -> dict[str, object]:
        return self._client().metrics.status().to_dict()

    def metrics_preview(self) -> dict[str, object]:
        """Exactly the batch that would be sent next, and how big it is."""
        batch = self._client().metrics.preview()
        return {"batch": batch.to_dict(), "size_bytes": batch.size_bytes}

    def metrics_send(self, force: bool) -> dict[str, object]:
        return self._client().metrics.send(force).to_dict()

    def metrics_opt_in(self) -> dict[str, object]:
        return self._client().metrics.opt_in().to_dict()

    def metrics_dismiss_prompt(self) -> dict[str, object]:
        self._client()._metrics_engine().dismiss_prompt()  # noqa: SLF001
        return self._client().metrics.status().to_dict()

    def metrics_rotate_id(self) -> dict[str, object]:
        self._client().metrics.rotate_id()
        return self._client().metrics.status().to_dict()

    def metrics_delete(self) -> dict[str, object]:
        return self._client().metrics.delete_data().to_dict()

    # ----- the processing tiers ---------------------------------------------------------------

    def tiers(self) -> list[dict[str, object]]:
        return [t.to_dict() for t in self._client().tiers.list()]

    def tiers_use(self, tier: str) -> dict[str, object]:
        return self._client().tiers.set(tier).to_dict()

    def tiers_reset(self) -> dict[str, object]:
        return self._client().tiers.reset().to_dict()
