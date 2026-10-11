"""Processing tiers: where the pages that need OCR are read.

VethuQ always extracts a file's pages, decides which need OCR, and renders them on this computer.
A *tier* decides where the OCR itself runs. `local` is built into VethuQ; an add-on can provide
another (for example `github`) by returning a `TierSpec` with an `OcrExecutor`.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from vethuq_addon_api.api import LanguageSpec
from vethuq_addon_api.ocr import OcrResult


@dataclass(frozen=True)
class OcrRequest:
    """One image to read.

    `key` identifies it in the answer (VethuQ makes it unique per page and region). `image` is
    what an OCR engine accepts: an image file path or a BGR pixel array. `phase` is the OCR phase
    asking (`quick`), `size_factor` the page's size against A4 (see docs/credits.md).
    """

    key: str
    image: Any
    language: LanguageSpec
    phase: str = "quick"
    size_factor: float = 1.0


class JobState(enum.StrEnum):
    """Where a submitted batch is (asynchronous executors only)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class OcrExecutor(ABC):
    """Reads images with OCR somewhere.

    A *synchronous* executor (`asynchronous = False`) implements `recognize`, which returns when
    the image has been read. It is called from several threads at once, so it must be thread-safe
    (or keep its state per thread).

    An *asynchronous* executor (`asynchronous = True`) takes batches that finish later: `submit`
    returns a handle (a short string VethuQ stores), `poll` says where it is, `collect` returns the
    results once it is done, and `cancel` abandons it. A handle must stay valid across restarts.
    """

    asynchronous: bool = False

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Read one image now. Raise `AddonError` if it can't be read."""
        raise NotImplementedError(f"{type(self).__name__} is asynchronous")

    def submit(self, requests: Sequence[OcrRequest]) -> str:
        """Start reading a batch. Returns its handle."""
        raise NotImplementedError(f"{type(self).__name__} is synchronous")

    def poll(self, handle: str) -> JobState:
        raise NotImplementedError(f"{type(self).__name__} is synchronous")

    def collect(self, handle: str) -> dict[str, OcrResult]:
        """The results of a batch that is `DONE`, by request key."""
        raise NotImplementedError(f"{type(self).__name__} is synchronous")

    def cancel(self, handle: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} is synchronous")

    @abstractmethod
    def describe(self) -> str:
        """Where this executor reads, for messages: for example `this computer`."""


@dataclass(frozen=True)
class TierSpec:
    """A processing tier an add-on provides.

    `id` is the short name users pass around (`"github"`); `wallet` names the credit wallet the
    tier's work is paid from. A tier that exists but can't be used right now is returned with
    `available=False` and a `reason`, rather than left out.
    """

    id: str
    label: str
    wallet: str
    executor: OcrExecutor | None = None
    available: bool = True
    reason: str = ""
