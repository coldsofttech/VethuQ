"""The catalog client: fetch, verify, cache, and fall back to an empty catalog.

It works like the policy client and shares its parts (keys, mirrors, fetcher, envelope check), with
its own cached file and its own sequence counter. Nothing here runs on import or when a client is
created. `current()` never touches the network; only `refresh()` does, and neither raises: a
failure keeps the last good catalog, so offline use and local work are never blocked.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from vethuq._catalog.model import Catalog, CatalogResult
from vethuq._policy.envelope import _EnvelopeVerifier
from vethuq._policy.errors import (
    _PolicyError,
    _PolicyFormatError,
    _RollbackError,
    _SchemaTooNewError,
)
from vethuq._policy.fetch import _FetchFailure, _PolicyFetcher
from vethuq._policy.keys import _PolicyKeys, _PolicyUrls
from vethuq._policy.state import _PolicyState, _PolicyStore
from vethuq.enums import PolicySource, PolicyStatus

_default_logger = logging.getLogger("vethuq.policy")
_default_logger.addHandler(logging.NullHandler())


class _CatalogStore(_PolicyStore):
    """The catalog's files, beside the policy's: `catalog.json` and `catalog-state.json`."""

    POLICY_FILENAME = "catalog.json"
    STATE_FILENAME = "catalog-state.json"


class _CatalogUrls:
    FILENAME = "catalog.json"

    @staticmethod
    def resolve(environ: dict[str, str] | None = None) -> tuple[str, ...]:
        """Where the catalog is: next to wherever the policy is (same hosts, same mirrors)."""
        found: list[str] = []
        for url in _PolicyUrls.resolve(environ):
            parsed = urlparse(url)
            folder, _, _name = parsed.path.rpartition("/")
            swapped = parsed._replace(path=f"{folder}/{_CatalogUrls.FILENAME}").geturl()
            if swapped not in found:
                found.append(swapped)
        return tuple(found)


class _CatalogClient:
    CHECK_INTERVAL_SECONDS = 24 * 60 * 60
    RETRY_INTERVAL_SECONDS = 60 * 60
    SUPPORTED_SCHEMA = 1

    def __init__(
        self,
        directory: Path,
        *,
        keys: _PolicyKeys | None = None,
        urls: tuple[str, ...] | None = None,
        fetcher: _PolicyFetcher | None = None,
        clock: Callable[[], float] = time.time,
        revoked: Callable[[], frozenset[str]] = frozenset,
        enabled: Callable[[], bool] = lambda: True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or _default_logger
        self._keys = keys or _PolicyKeys.embedded()
        self._verifier = _EnvelopeVerifier(self._keys)
        self._fetcher = fetcher or _PolicyFetcher(urls or _CatalogUrls.resolve())
        self._store = _CatalogStore(directory)
        self._clock = clock
        self._revoked = revoked
        self._enabled = enabled
        self._lock = threading.RLock()

    def current(self) -> CatalogResult:
        """The catalog to use now: the cached one, else an empty one. No network."""
        return self._describe(PolicyStatus.CURRENT, self._store.read_state())

    def refresh(self, force: bool = False) -> CatalogResult:
        """Check for a newer catalog (at most about once a day unless `force`). Never raises."""
        with self._lock:
            try:
                return self._refresh(force)
            except Exception:  # a catalog problem must never reach the caller
                self._logger.exception("catalog refresh failed")
                return self._describe(
                    PolicyStatus.OFFLINE, self._store.read_state(), "unexpected error"
                )

    def refresh_in_background(self, force: bool = False) -> threading.Thread:
        thread = threading.Thread(
            target=self.refresh, kwargs={"force": force}, name="vethuq-catalog", daemon=True
        )
        thread.start()
        return thread

    # ----- fetching -----------------------------------------------------------------------

    def _refresh(self, force: bool) -> CatalogResult:
        state = self._store.read_state()
        if not self._enabled():
            return self._describe(PolicyStatus.SKIPPED, state, "the update check is turned off")
        if not self._keys.kids:
            return self._describe(PolicyStatus.SKIPPED, state, "no policy keys are embedded yet")
        now = self._clock()
        if not force and self._recently_checked(state, now):
            return self._describe(PolicyStatus.SKIPPED, state)

        cached = self._verified_cache(state)
        failures: list[str] = []
        rejected = False
        for attempt in self._fetcher.attempts(state.etag_url, state.etag):
            if isinstance(attempt, _FetchFailure):
                failures.append(f"{attempt.url}: {attempt.reason}")
                continue
            if attempt.not_modified:
                state = replace(state, last_check=now, last_failure=0.0)
                self._save(state)
                return self._describe(PolicyStatus.UNCHANGED, state)
            assert attempt.body is not None  # noqa: S101 - set when the fetch did not fail
            try:
                catalog = self._verify(attempt.body, state)
                if cached is not None and cached.raw == catalog.raw:
                    state = replace(
                        state,
                        etag=attempt.etag,
                        etag_url=attempt.url if attempt.etag else None,
                        last_check=now,
                        last_failure=0.0,
                    )
                    self._save(state)
                    return self._describe(PolicyStatus.UNCHANGED, state)
                self._check_sequence(catalog, state)
            except _SchemaTooNewError as exc:
                state = replace(state, update_required=True, last_check=now, last_failure=0.0)
                self._save(state)
                return self._describe(PolicyStatus.UPDATE_REQUIRED, state, str(exc))
            except _PolicyError as exc:
                rejected = True
                failures.append(f"{attempt.url}: {exc}")
                continue
            return self._accept(attempt.body, attempt.url, attempt.etag, catalog, state, now)

        state = replace(state, last_failure=now)
        self._save(state)
        status = PolicyStatus.REJECTED if rejected else PolicyStatus.OFFLINE
        return self._describe(status, state, "; ".join(failures))

    def _verify(self, raw: bytes, state: _PolicyState) -> Catalog:
        """The catalog in an envelope signed by a trusted, unrevoked key. The payload is parsed
        only after the signature has checked out."""
        signed = self._verifier.verify_signed(raw, self._revoked())
        try:
            data = json.loads(signed.payload)
        except ValueError as exc:
            raise _PolicyFormatError("payload is not valid JSON") from exc
        if not isinstance(data, dict):
            raise _PolicyFormatError("payload is not a JSON object")
        if data.get("kid") != signed.kid:
            raise _PolicyFormatError("payload kid does not match the envelope kid")
        schema = data.get("schema_version")
        if isinstance(schema, int) and not isinstance(schema, bool):
            if schema > self.SUPPORTED_SCHEMA:
                raise _SchemaTooNewError(f"schema version {schema} is newer than supported")
            if schema < 1:
                raise _PolicyFormatError("schema_version must be at least 1")
        return Catalog.from_payload(data)

    @staticmethod
    def _check_sequence(catalog: Catalog, state: _PolicyState) -> None:
        floor = state.accepted.get(catalog.kid, 0)
        if catalog.sequence <= floor:
            raise _RollbackError(
                f"sequence {catalog.sequence} is not above {floor} for key {catalog.kid!r}"
            )

    def _accept(
        self,
        raw: bytes,
        url: str,
        etag: str | None,
        catalog: Catalog,
        state: _PolicyState,
        now: float,
    ) -> CatalogResult:
        state = replace(
            state.with_accepted(catalog.kid, catalog.sequence),
            etag=etag,
            etag_url=url if etag else None,
            last_check=now,
            last_failure=0.0,
            update_required=False,
        )
        detail = ""
        try:
            self._store.write_envelope(raw)
            self._store.write_state(state)
        except OSError as exc:
            self._logger.warning("could not save the catalog cache: %s", exc)
            detail = f"catalog not cached: {exc}"
        self._logger.info("accepted catalog sequence %d from %s", catalog.sequence, url)
        return CatalogResult(catalog, PolicySource.FETCHED, PolicyStatus.UPDATED, detail)

    def _recently_checked(self, state: _PolicyState, now: float) -> bool:
        if state.last_failure and now - state.last_failure < self.RETRY_INTERVAL_SECONDS:
            return True
        return bool(state.last_check) and now - state.last_check < self.CHECK_INTERVAL_SECONDS

    def _verified_cache(self, state: _PolicyState) -> Catalog | None:
        """The cached catalog, verified again; a damaged, unknown-key or revoked one is ignored."""
        raw = self._store.read_envelope()
        if raw is None:
            return None
        try:
            return self._verify(raw, state)
        except _PolicyError as exc:
            self._logger.warning("ignoring the cached catalog: %s", exc)
            return None

    def _describe(
        self, status: PolicyStatus, state: _PolicyState, detail: str = ""
    ) -> CatalogResult:
        cached = self._verified_cache(state)
        catalog, source = (
            (cached, PolicySource.CACHE) if cached else (self._baseline(), PolicySource.BASELINE)
        )
        return CatalogResult(catalog, source, status, detail, state.update_required)

    @staticmethod
    def _baseline() -> Catalog:
        """No catalog yet: nothing is listed beyond what is installed."""
        return Catalog(1, 0, datetime(1970, 1, 1, tzinfo=UTC), "baseline")

    def _save(self, state: _PolicyState) -> None:
        try:
            self._store.write_state(state)
        except OSError as exc:
            self._logger.warning("could not save the catalog state: %s", exc)
