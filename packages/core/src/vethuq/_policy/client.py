"""The policy client: fetch, verify, cache, and fall back to the baseline.

Nothing here runs on import or when a client is created. `current()` never touches the network;
only `refresh()` does, and neither raises: a failure keeps the last good policy (or the baseline
when there is none), so offline use and local work are never blocked.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from vethuq._policy.baseline import _Baseline
from vethuq._policy.envelope import _EnvelopeVerifier, _VerifiedEnvelope
from vethuq._policy.errors import _PolicyError, _SchemaTooNewError
from vethuq._policy.fetch import _FetchFailure, _PolicyFetcher
from vethuq._policy.keys import _PolicyKeys, _PolicyUrls
from vethuq._policy.model import PolicyResult
from vethuq._policy.rules import _SequenceRules
from vethuq._policy.state import _PolicyState, _PolicyStore
from vethuq.enums import PolicySource, PolicyStatus

_default_logger = logging.getLogger("vethuq.policy")
_default_logger.addHandler(logging.NullHandler())  # never print to stderr when nobody listens


class _PolicyClient:
    CHECK_INTERVAL_SECONDS = 24 * 60 * 60
    RETRY_INTERVAL_SECONDS = 60 * 60

    def __init__(
        self,
        directory: Path,
        *,
        keys: _PolicyKeys | None = None,
        urls: tuple[str, ...] | None = None,
        fetcher: _PolicyFetcher | None = None,
        clock: Callable[[], float] = time.time,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or _default_logger
        self._keys = keys or _PolicyKeys.embedded()
        self._verifier = _EnvelopeVerifier(self._keys)
        self._rules = _SequenceRules(self._keys)
        self._fetcher = fetcher or _PolicyFetcher(urls or _PolicyUrls.resolve())
        self._store = _PolicyStore(directory)
        self._clock = clock
        self._lock = threading.RLock()

    def current(self) -> PolicyResult:
        """The policy to use now: the cached one, else the baseline. No network."""
        # No lock: a refresh can be mid-request, and files are replaced atomically.
        return self._describe(PolicyStatus.CURRENT, self._store.read_state())

    def refresh(self, force: bool = False) -> PolicyResult:
        """Check for a newer policy (at most about once a day unless `force`). Never raises."""
        with self._lock:
            try:
                return self._refresh(force)
            except Exception:  # a policy problem must never reach the caller
                self._logger.exception("policy refresh failed")
                return self._describe(
                    PolicyStatus.OFFLINE, self._store.read_state(), "unexpected error"
                )

    def refresh_in_background(self, force: bool = False) -> threading.Thread:
        """Run `refresh` on a daemon thread so startup is never delayed."""
        thread = threading.Thread(
            target=self.refresh, kwargs={"force": force}, name="vethuq-policy", daemon=True
        )
        thread.start()
        return thread

    def _refresh(self, force: bool) -> PolicyResult:
        state = self._store.read_state()
        if not self._keys.kids:
            # Nothing could be verified, so there is no point in a request.
            return self._describe(PolicyStatus.SKIPPED, state, "no policy keys are embedded yet")
        now = self._clock()
        if not force and self._recently_checked(state, now):
            return self._describe(PolicyStatus.SKIPPED, state)

        cached = self._load_cached(state)
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
            assert attempt.body is not None  # noqa: S101 - narrows the type; set when not failed
            try:
                verified = self._verifier.verify(attempt.body, state.revoked)
                if cached and (cached.kid, cached.payload) == (verified.kid, verified.payload):
                    state = replace(
                        state,
                        etag=attempt.etag,
                        etag_url=attempt.url if attempt.etag else None,
                        last_check=now,
                        last_failure=0.0,
                    )
                    self._save(state)
                    return self._describe(PolicyStatus.UNCHANGED, state)
                self._rules.check(verified, state)
            except _SchemaTooNewError as exc:
                # Signed by a trusted key but needs a newer VethuQ: keep the last compatible one.
                state = replace(state, update_required=True, last_check=now, last_failure=0.0)
                self._save(state)
                return self._describe(PolicyStatus.UPDATE_REQUIRED, state, str(exc))
            except _PolicyError as exc:
                rejected = True
                failures.append(f"{attempt.url}: {exc}")
                continue
            return self._accept(attempt.body, attempt.url, attempt.etag, verified, state, now)

        state = replace(state, last_failure=now)
        self._save(state)
        status = PolicyStatus.REJECTED if rejected else PolicyStatus.OFFLINE
        return self._describe(status, state, "; ".join(failures))

    def _accept(
        self,
        raw: bytes,
        url: str,
        etag: str | None,
        verified: _VerifiedEnvelope,
        state: _PolicyState,
        now: float,
    ) -> PolicyResult:
        state = self._rules.accept(verified, state)
        state = replace(
            state,
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
            self._logger.warning("could not save the policy cache: %s", exc)
            detail = f"policy not cached: {exc}"
        self._logger.info("accepted policy sequence %d from %s", verified.policy.sequence, url)
        return PolicyResult(verified.policy, PolicySource.FETCHED, PolicyStatus.UPDATED, detail)

    def _recently_checked(self, state: _PolicyState, now: float) -> bool:
        if state.last_failure and now - state.last_failure < self.RETRY_INTERVAL_SECONDS:
            return True
        return bool(state.last_check) and now - state.last_check < self.CHECK_INTERVAL_SECONDS

    def _load_cached(self, state: _PolicyState) -> _VerifiedEnvelope | None:
        """The cached envelope, verified again; a damaged, unknown-key or revoked one is ignored."""
        raw = self._store.read_envelope()
        if raw is None:
            return None
        try:
            return self._verifier.verify(raw, state.revoked)
        except _PolicyError as exc:
            self._logger.warning("ignoring the cached policy: %s", exc)
            return None

    def _describe(
        self, status: PolicyStatus, state: _PolicyState, detail: str = ""
    ) -> PolicyResult:
        cached = self._load_cached(state)
        policy, source = (
            (cached.policy, PolicySource.CACHE)
            if cached
            else (_Baseline.policy(), PolicySource.BASELINE)
        )
        message = PolicyResult.UPDATE_MESSAGE if state.update_required else ""
        return PolicyResult(policy, source, status, detail or message, state.update_required)

    def _save(self, state: _PolicyState) -> None:
        try:
            self._store.write_state(state)
        except OSError as exc:
            self._logger.warning("could not save the policy state: %s", exc)
