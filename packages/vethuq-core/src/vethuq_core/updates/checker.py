"""Compare this VethuQ with the signed policy's `latest` and `minimum_supported`."""

from __future__ import annotations

import logging
import time
from dataclasses import replace

from vethuq_core.policy import PolicyResult, PolicyService, PolicySource
from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import Storage
from vethuq_core.updates.distribution import Distribution
from vethuq_core.updates.result import UpdateResult, UpdateStatus
from vethuq_core.updates.versions import Versions

_default_logger = logging.getLogger("vethuq.updates")
_default_logger.addHandler(logging.NullHandler())


class UpdateChecker:
    """Neither method raises: a problem means "unknown", never a blocked start or command."""

    @staticmethod
    def status(
        storage: Storage,
        logger: logging.Logger | None = None,
        policy_result: PolicyResult | None = None,
    ) -> UpdateResult:
        """What the saved policy says about this version. Makes no network request."""
        current = "unknown"
        distribution = Distribution.current()
        try:
            current = Versions.installed()
            mode = UpdateSettings.effective_check(storage)
            if mode == "off":
                return UpdateResult(
                    UpdateStatus.DISABLED,
                    mode,
                    current,
                    distribution,
                    disabled_by_environment=UpdateSettings.disabled_by_environment(),
                )
            result = policy_result or PolicyService.current(logger)
            return UpdateChecker.evaluate(storage, result, mode, current, distribution)
        except Exception:  # noqa: BLE001 - an update check must never get in the way
            (logger or _default_logger).warning("Update status unavailable", exc_info=True)
            return UpdateResult(UpdateStatus.UNKNOWN, "on", current, distribution)

    @staticmethod
    def check(
        storage: Storage, force: bool = False, logger: logging.Logger | None = None
    ) -> UpdateResult:
        """Refresh the policy (at most about once a day unless `force`) and report on it.

        Does nothing on the network when the check is switched off.
        """
        try:
            if UpdateSettings.effective_check(storage) != "off":
                return UpdateChecker.status(
                    storage, logger, PolicyService.client(logger).refresh(force=force)
                )
        except Exception:  # noqa: BLE001
            (logger or _default_logger).warning("Update check failed", exc_info=True)
        return UpdateChecker.status(storage, logger)

    @staticmethod
    def evaluate(
        storage: Storage,
        policy_result: PolicyResult,
        mode: str,
        current: str,
        distribution: str,
        now: float | None = None,
    ) -> UpdateResult:
        """The pure comparison, with the user's snooze and skip applied."""
        moment = time.time() if now is None else now
        unknown = UpdateResult(
            UpdateStatus.UNKNOWN,
            mode,
            current,
            distribution,
            snoozed=UpdateSettings.is_snoozed(storage, moment),
            policy_update_required=policy_result.update_required,
        )
        entry = policy_result.policy.versions.get(distribution)
        if entry is None or policy_result.source is PolicySource.BASELINE:
            return unknown
        if Versions.parse(current) is None or Versions.parse(entry.latest) is None:
            return unknown

        known = replace(
            unknown,
            latest=entry.latest,
            minimum_supported=entry.minimum_supported,
            release_notes_url=entry.release_notes_url,
        )
        if Versions.is_older(current, entry.minimum_supported):
            return replace(known, status=UpdateStatus.BELOW_MINIMUM)
        if Versions.is_older(current, entry.latest):
            return replace(
                known,
                status=UpdateStatus.AVAILABLE,
                skipped=UpdateSettings.get_skipped_version(storage) == entry.latest,
            )
        return replace(known, status=UpdateStatus.UP_TO_DATE)
