"""Worker scheduling: how many files VethuQ reads side by side while a run is going."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Footprint:
    """What reading one file took, as VethuQ recorded it."""

    size_bytes: int
    pages: int
    seconds: float
    workers: int  # files being read at the same time, this one included


@dataclass(frozen=True)
class WorkPlan:
    """What VethuQ tells a scheduler each time it asks how many files may be read at once."""

    ceiling: int  # the most VethuQ will ever use (its own estimate for this machine)
    active: int  # files being read now
    queued: int  # files waiting
    history: tuple[Footprint, ...] = ()  # recent footprints, newest last (may be empty)


class WorkerScheduler(ABC):
    """Decides, while a run is going, how many files are read at once.

    VethuQ asks only when the `workers` setting is `auto`; a fixed number is always honoured. The
    answer is clamped to 1..`plan.ceiling`, and VethuQ always lets one file run, so a scheduler can
    slow a run but never stop it."""

    @abstractmethod
    def allowed(self, plan: WorkPlan) -> int:
        """How many files may be read at once right now."""
