"""The GitHub owner a job runs for, held against the licences in its manifest.

The caller workflow (pinned, so it can't be edited to lie) gives the worker the numeric id of the
repository's owner, a user or an organisation. A licence that lists owner ids
(`binding.github_owner_ids`) is refused when that id isn't one of them. A licence with no owner
list, and every job run outside GitHub, is not affected. Membership of an organisation isn't
checked: the owner list is the licensee's own statement of which accounts may run the licence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from vethuq_worker.errors import JobError

VARIABLE = "VETHUQ_GITHUB_OWNER_ID"
LICENCE_KEY = "licence"
Verifier = Callable[..., Any]


class OwnerCheck:
    @staticmethod
    def owner_id(environment: Mapping[str, str] | None = None) -> int | None:
        """The owner id the workflow gave, or None (not running for GitHub, or not given)."""
        raw = (os.environ if environment is None else environment).get(VARIABLE, "").strip()
        if not raw:
            return None
        if not raw.isdigit():
            raise JobError("owner_mismatch", "The runner's owner id isn't a number.")
        return int(raw)

    @staticmethod
    def default_verifier() -> Verifier | None:
        try:
            from vethuq_entitlements import Licences
        except ImportError:  # no entitlements: nothing here is licensed
            return None
        return Licences().verify

    @classmethod
    def check(
        cls,
        addon_settings: Mapping[str, Mapping[str, str]],
        owner_id: int | None,
        verifier: Verifier | None = None,
    ) -> None:
        """Raises `JobError("owner_mismatch")` when a licence in the manifest is for other
        GitHub owners than `owner_id`."""
        if owner_id is None:
            return
        verify = verifier or cls.default_verifier()
        if verify is None:
            return
        for token in {s.get(LICENCE_KEY) for s in addon_settings.values()} - {None, ""}:
            status = getattr(verify(token, github_owner_id=owner_id), "status", None)
            if getattr(status, "name", str(status)).upper().endswith("OWNER_MISMATCH"):
                raise JobError(
                    "owner_mismatch",
                    "A licence in this job is for another GitHub account. Ask for a licence "
                    "that lists the owner of your runner repository.",
                )
