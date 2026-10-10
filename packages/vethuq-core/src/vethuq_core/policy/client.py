"""The policy client: fetch, verify, cache, and fall back to the baseline.

Nothing here runs on import. `current()` never touches the network; only `refresh()` does, and
neither raises: a failure keeps the last good policy (or the baseline when there is none), so
offline use and local work are never blocked.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from vethuq_core.paths import Paths
from vethuq_core.policy.baseline import Baseline
from vethuq_core.policy.envelope import EnvelopeVerifier, VerifiedEnvelope
from vethuq_core.policy.errors import PolicyError, SchemaTooNewError
from vethuq_core.policy.fetch import FetchFailure, PolicyFetcher
from vethuq_core.policy.keys import PolicyKeys, PolicyUrls
from vethuq_core.policy.model import Policy
from vethuq_core.policy.rules import SequenceRules
from vethuq_core.policy.state import PolicyState, PolicyStore

logger = logging.getLogger("vethuq.policy")


class PolicySource(StrEnum):
    FETCHED = "fetched"  # accepted by this call
    CACHE = "cache"  # the last accepted policy, re-verified from disk
    BASELINE = "baseline"  # the built-in policy


class PolicyStatus(StrEnum):
    CURRENT = "current"  # `current()`: nothing was fetched
    UPDATED = "updated"  # a newer policy was accepted
    UNCHANGED = "unchanged"  # the server has nothing newer
    SKIPPED = "skipped"  # checked recently; no request made
    OFFLINE = "offline"  # every URL failed (network, timeout, size, HTTP error)
    REJECTED = "rejected"  # every URL answered but nothing was acceptable
    UPDATE_REQUIRED = "update_required"  # the policy needs a newer VethuQ than this one


@dataclass(frozen=True)
class PolicyResult:
    policy: Policy
    source: PolicySource
    status: PolicyStatus
    detail: str = ""
    update_required: bool = False

    UPDATE_MESSAGE = "Update VethuQ to receive new policy."


class PolicyClient:
    CHECK_INTERVAL_SECONDS = 24 * 60 * 60
    RETRY_INTERVAL_SECONDS = 60 * 60
    CACHE_DIRNAME = "policy"

    def __init__(
        self,
        *,
        keys: PolicyKeys | None = None,
        urls: tuple[str, ...] | None = None,
        cache_dir: Path | None = None,
        fetcher: PolicyFetcher | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._keys = keys or PolicyKeys.embedded()
        self._verifier = EnvelopeVerifier(self._keys)
        self._rules = SequenceRules(self._keys)
        self._fetcher = fetcher or PolicyFetcher(urls or PolicyUrls.DEFAULT)
        self._store = PolicyStore(cache_dir or Paths.default_data_root() / self.CACHE_DIRNAME)
        self._clock = clock
        self._lock = threading.RLock()

    def current(self) -> PolicyResult:
        """The policy to use now: the cached one, else the baseline. No network."""
        with self._lock:
            return self._describe(PolicyStatus.CURRENT, self._store.read_state())

    def refresh(self, force: bool = False) -> PolicyResult:
        """Check for a newer policy (at most about once a day unless `force`). Never raises."""
        with self._lock:
            try:
                return self._refresh(force)
            except Exception:  # a policy problem must never reach the caller
                logger.exception("policy refresh failed")
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
        now = self._clock()
        if not force and self._recently_checked(state, now):
            return self._describe(PolicyStatus.SKIPPED, state)

        cached = self._load_cached(state)
        failures: list[str] = []
        rejected = False
        for attempt in self._fetcher.attempts(state.etag_url, state.etag):
            if isinstance(attempt, FetchFailure):
                failures.append(f"{attempt.url}: {attempt.reason}")
                continue
            if attempt.not_modified:
                state = replace(state, last_check=now, last_failure=0.0)
                self._save(state)
                return self._describe(PolicyStatus.UNCHANGED, state)
            assert attempt.body is not None
            try:
                verified = self._verifier.verify(attempt.body, state.revoked)
                if cached and (cached.kid, cached.payload) == (verified.kid, verified.payload):
                    state = replace(
                        state, etag=attempt.etag, etag_url=attempt.url if attempt.etag else None
                    )
                    state = replace(state, last_check=now, last_failure=0.0)
                    self._save(state)
                    return self._describe(PolicyStatus.UNCHANGED, state)
                self._rules.check(verified, state)
            except SchemaTooNewError as exc:
                # Signed by a trusted key but needs a newer VethuQ: keep the last compatible one.
                state = replace(state, update_required=True, last_check=now, last_failure=0.0)
                self._save(state)
                return self._describe(PolicyStatus.UPDATE_REQUIRED, state, str(exc))
            except PolicyError as exc:
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
        verified: VerifiedEnvelope,
        state: PolicyState,
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
            logger.warning("could not save the policy cache: %s", exc)
            detail = f"policy not cached: {exc}"
        return PolicyResult(verified.policy, PolicySource.FETCHED, PolicyStatus.UPDATED, detail)

    def _recently_checked(self, state: PolicyState, now: float) -> bool:
        if state.last_failure and now - state.last_failure < self.RETRY_INTERVAL_SECONDS:
            return True
        return bool(state.last_check) and now - state.last_check < self.CHECK_INTERVAL_SECONDS

    def _load_cached(self, state: PolicyState) -> VerifiedEnvelope | None:
        """The cached envelope, verified again; a damaged, unknown-key or revoked one is ignored."""
        raw = self._store.read_envelope()
        if raw is None:
            return None
        try:
            return self._verifier.verify(raw, state.revoked)
        except PolicyError as exc:
            logger.warning("ignoring the cached policy: %s", exc)
            return None

    def _describe(self, status: PolicyStatus, state: PolicyState, detail: str = "") -> PolicyResult:
        cached = self._load_cached(state)
        policy, source = (
            (cached.policy, PolicySource.CACHE)
            if cached
            else (Baseline.policy(), PolicySource.BASELINE)
        )
        message = PolicyResult.UPDATE_MESSAGE if state.update_required else ""
        return PolicyResult(policy, source, status, detail or message, state.update_required)

    def _save(self, state: PolicyState) -> None:
        try:
            self._store.write_state(state)
        except OSError as exc:
            logger.warning("could not save the policy state: %s", exc)
