"""Running pages through a reader and checking the scores against the limits in `thresholds.json`.

The reader is anything with `read(image, phase, language) -> Reading`; `engines.py` has the one for
the real engine, tests use fakes. A case is a phase, a language and a page type. It passes when its
scores are inside the limits for that combination, fails when they are not (or the read raises),
and is only reported when no limit is set for it.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from tools.ocr_accuracy import pages, score

THRESHOLDS = Path(__file__).with_name("thresholds.json")
PASS, FAIL, UNCHECKED, SKIPPED = "pass", "fail", "unchecked", "skipped"


@dataclass(frozen=True)
class Reading:
    """What a read gave: the text and the engine's confidence (0 to 1)."""

    text: str
    confidence: float


class Reader(Protocol):
    def read(self, image: np.ndarray, phase: str, language: str) -> Reading: ...


@dataclass
class Result:
    phase: str
    language: str
    page_type: str
    status: str
    cer: float | None = None
    word_recall: float | None = None
    confidence: float | None = None
    seconds: float | None = None
    peak_rss_mb: float | None = None  # the process's high-water mark so far, not this case alone
    note: str = ""
    limits: dict[str, float] = field(default_factory=dict)


def peak_rss_mb() -> float | None:
    """The process's peak resident memory in MB, or None where it can't be read (Windows)."""
    try:
        import resource  # noqa: PLC0415 - not available everywhere
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(usage / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


def load_thresholds(path: Path = THRESHOLDS) -> dict[str, Any]:
    return json.loads(Path(path).read_text("utf-8"))


def limits_for(thresholds: Mapping[str, Any], phase: str, page_type: str) -> dict[str, float]:
    return dict(thresholds.get("limits", {}).get(phase, {}).get(page_type, {}))


def judge(cer: float, recall: float, limits: Mapping[str, float]) -> str:
    """`unchecked` without limits, else `pass` or `fail`."""
    if not limits:
        return UNCHECKED
    ok = cer <= limits.get("max_cer", float("inf")) and recall >= limits.get("min_word_recall", 0.0)
    return PASS if ok else FAIL


def run_case(
    reader: Reader,
    phase: str,
    language: str,
    page_type: str,
    thresholds: Mapping[str, Any],
    clock: Callable[[], float] = time.perf_counter,
    rss: Callable[[], float | None] = peak_rss_mb,
) -> Result:
    limits = limits_for(thresholds, phase, page_type)
    try:
        page = pages.make(page_type, language)
    except (pages.FontNotFound, KeyError) as error:
        return Result(phase, language, page_type, SKIPPED, note=str(error), limits=limits)
    started = clock()
    try:
        reading = reader.read(page.image, phase, language)
    except Exception as error:  # noqa: BLE001 - a failing read is a failing case, not a crash
        return Result(
            phase,
            language,
            page_type,
            FAIL,
            seconds=round(clock() - started, 2),
            peak_rss_mb=rss(),
            note=f"{type(error).__name__}: {error}",
            limits=limits,
        )
    seconds = round(clock() - started, 2)
    cer = round(score.cer(page.reference, reading.text), 4)
    recall = round(score.word_recall(page.reference, reading.text), 4)
    return Result(
        phase,
        language,
        page_type,
        judge(cer, recall, limits),
        cer=cer,
        word_recall=recall,
        confidence=round(reading.confidence, 4),
        seconds=seconds,
        peak_rss_mb=rss(),
        limits=limits,
    )


@dataclass
class Report:
    results: list[Result]
    thresholds_provisional: bool = False

    @property
    def failed(self) -> list[Result]:
        return [r for r in self.results if r.status == FAIL]

    def to_dict(self) -> dict[str, Any]:
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "thresholds_provisional": self.thresholds_provisional,
            "summary": {
                status: sum(1 for r in self.results if r.status == status)
                for status in (PASS, FAIL, UNCHECKED, SKIPPED)
            },
            "results": [asdict(r) for r in self.results],
        }

    def markdown(self) -> str:
        """A table for the workflow's step summary."""
        counts = self.to_dict()["summary"]
        lines = ["### OCR accuracy", "", ", ".join(f"{n} {s}" for s, n in counts.items()), ""]
        if self.thresholds_provisional:
            lines += [
                "_The limits are provisional: a failure may mean a limit needs calibrating._",
                "",
            ]
        lines += [
            "| phase | language | page | status | CER | word recall | confidence | seconds "
            "| peak MB |",
            "|---|---|---|---|---|---|---|---|---|",
        ]

        def cell(value: object) -> str:
            return "-" if value is None else str(value)

        for r in self.results:
            lines.append(
                f"| {r.phase} | {r.language} | {r.page_type} | {r.status} | {cell(r.cer)} | "
                f"{cell(r.word_recall)} | {cell(r.confidence)} | {cell(r.seconds)} | "
                f"{cell(r.peak_rss_mb)} |"
            )
        notes = [
            f"- {r.phase}/{r.language}/{r.page_type}: {r.note}" for r in self.results if r.note
        ]
        return "\n".join([*lines, "", *notes]) + "\n"

    def suggested_thresholds(self) -> dict[str, Any]:
        """Limits that today's scores would pass, with room: use them to calibrate a new engine or
        page type (review them before committing them)."""
        limits: dict[str, dict[str, dict[str, float]]] = {}
        for r in self.results:
            if r.cer is None or r.word_recall is None:
                continue
            limits.setdefault(r.phase, {})[r.page_type] = {
                "max_cer": round(r.cer * 1.5 + 0.01, 3),
                "min_word_recall": round(max(0.0, r.word_recall - 0.05), 3),
            }
        return {"version": 1, "provisional": True, "limits": limits}


def run(
    reader: Reader,
    phases: Sequence[str],
    languages: Sequence[str],
    page_types: Iterable[str],
    thresholds: Mapping[str, Any],
    clock: Callable[[], float] = time.perf_counter,
    rss: Callable[[], float | None] = peak_rss_mb,
) -> Report:
    chosen = list(page_types)
    results = [
        run_case(reader, phase, language, page_type, thresholds, clock, rss)
        for phase in phases
        for language in languages
        for page_type in chosen
    ]
    return Report(results, bool(thresholds.get("provisional")))
