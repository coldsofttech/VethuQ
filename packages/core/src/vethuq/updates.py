"""The update check: `VethuQ().updates`.

VethuQ compares its own version with the signed policy (`VethuQ().policy`): the policy is the only
source, so an update is announced only when it is published there and the answer is
signature-checked. Local work is never blocked: below the minimum version, indexing, search and your
data keep working, and only features that need a newer VethuQ are held back.

    result = client.updates.check()
    if result.notify:
        print(result.message)
"""

from __future__ import annotations

import logging

from vethuq._db import _Database
from vethuq._logs import _PolicyLog
from vethuq._settings import _UpdateSettings, _UpdateView
from vethuq._updates import (
    FeatureAccess,
    UpdateResult,
    _Distribution,
    _FeatureGate,
    _UpdateChecker,
    _Versions,
)
from vethuq.enums import UpdateCheckMode, UpdateStatus
from vethuq.policy import PolicyClient

__all__ = ["FeatureAccess", "UpdateCheckMode", "UpdateResult", "UpdateStatus", "Updates"]


class Updates:
    """Tells you when a newer VethuQ exists, and which features need one.

    Not created directly: use `VethuQ().updates`. Neither `status()` nor `check()` raises: a problem
    means "unknown", never a blocked start or command. Nothing is fetched when a client is
    created; only `check()` can use the network, and only when the check is not switched off.
    """

    def __init__(self, database: _Database, policy: PolicyClient) -> None:
        self._database = database
        self._policy = policy

    @property
    def _logger(self) -> logging.Logger:
        return _PolicyLog.logger()

    def _view(self) -> _UpdateView:
        """The update settings; if the database can't be read (it may be too new for this VethuQ,
        which is exactly when an update is needed), the defaults apply."""
        try:
            with self._database.session() as session:
                return _UpdateSettings.read(session)
        except Exception:  # noqa: BLE001 - an update check must never get in the way
            self._logger.warning("Update settings unavailable; using the defaults", exc_info=True)
            by_environment = _UpdateSettings.disabled_by_environment()
            mode = UpdateCheckMode.OFF if by_environment else _UpdateSettings.DEFAULT_CHECK
            return _UpdateView(mode=mode, disabled_by_environment=by_environment)

    def _result(self, view: _UpdateView, current: str, distribution: str, policy_result):
        if view.mode is UpdateCheckMode.OFF:
            return _UpdateChecker.disabled(current, distribution, view.disabled_by_environment)
        return _UpdateChecker.evaluate(
            policy_result,
            view.mode,
            current,
            distribution,
            snoozed=view.snoozed,
            skipped_version=view.skipped_version,
        )

    def status(self) -> UpdateResult:
        """What the saved policy says about this version. Makes no network request."""
        current, distribution = "unknown", _Distribution.current()
        try:
            current = _Versions.installed()
            view = self._view()
            policy_result = self._policy.current() if view.mode is not UpdateCheckMode.OFF else None
            return self._result(view, current, distribution, policy_result)
        except Exception:  # noqa: BLE001
            self._logger.warning("Update status unavailable", exc_info=True)
            return UpdateResult(UpdateStatus.UNKNOWN, UpdateCheckMode.ON, current, distribution)

    def check(self, force: bool = False) -> UpdateResult:
        """Refresh the policy (about once a day, or now with `force`) and report on it.

        Does nothing on the network when the check is switched off.
        """
        try:
            view = self._view()
            if view.mode is not UpdateCheckMode.OFF:
                policy_result = self._policy.refresh(force=force)
                return self._result(
                    view, _Versions.installed(), _Distribution.current(), policy_result
                )
        except Exception:  # noqa: BLE001
            self._logger.warning("Update check failed", exc_info=True)
        return self.status()

    def feature(self, name: str, default: bool) -> FeatureAccess:
        """Whether feature `name` is available to this VethuQ, and why not when it isn't.

        `default` is what the feature does when the policy doesn't cover it, so an older VethuQ
        keeps what already works. The policy can switch a feature off for everyone (a kill switch)
        or turn it on only for versions at or above its `min_client`; this VethuQ is then told it
        needs an update (`requires_update`). Makes no request and never raises.
        """
        try:
            policy = self._policy.current().policy
            return _FeatureGate.check(name, default, policy, _Versions.installed())
        except Exception:  # noqa: BLE001 - a policy problem must not stop local work
            return FeatureAccess(name, default)
