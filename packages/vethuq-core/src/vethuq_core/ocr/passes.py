"""The queued language passes: a file read again in the next candidate language.

After a file's first language has read it and doubted itself (see `LanguagePlan`), the other
candidate languages wait in `document_languages` as `pending` passes, English first and the rest
in order. Once every file has had its first pass, `LanguagePasses.run_batch` works through them:
it reads each scanned page again in the pass's language and adds the lines that language read
believably to what the page already says, so a page in two languages ends up with both. Each pass
is saved as soon as it is read, so stopping or crashing loses nothing.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from vethuq_core.languages import Scripts
from vethuq_core.logs import Logs
from vethuq_core.ocr.catalog import OcrCatalog, OcrComponentInfo
from vethuq_core.ocr.deepening import Deepening
from vethuq_core.ocr.detection import LanguageDetector
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.ocr.page import PageOcr
from vethuq_core.ocr.plan import LanguagePlan
from vethuq_core.ocr.quick import Quick
from vethuq_core.paths.extensions import Extensions
from vethuq_core.readers import Readers
from vethuq_core.readers.storage import PageStorage
from vethuq_core.sources import Source
from vethuq_core.storage import Row, Storage

_logger = Logs.get_logger("index")


@dataclass(frozen=True)
class LanguageUnit:
    """One queued pass: `language` over the file held by `document_index` row `document_id`."""

    document_id: int
    language: str
    position: int
    file_path: Path
    file_type: str

    @property
    def key(self) -> tuple[int, str]:
        return self.document_id, self.language

    @property
    def table(self) -> str:
        return "pdf_pages" if self.file_type == "pdf" else "image_pages"


class LanguagePasses:
    @staticmethod
    def find_units(
        storage: Storage, sources: list[Source], skip: set[tuple[int, str]] | None = None
    ) -> list[LanguageUnit]:
        """The next pending pass of each indexed file under `sources`, in queue order."""
        rows = storage.list_pending_language_passes([source.id for source in sources])
        return [
            LanguageUnit(
                document_id=row["document_id"],
                language=row["language"],
                position=row["position"],
                file_path=Path(row["file_path"]),
                file_type=row["file_type"],
            )
            for row in rows
            if skip is None or (row["document_id"], row["language"]) not in skip
        ]

    @staticmethod
    def has_pending(storage: Storage, sources: list[Source]) -> bool:
        return bool(storage.list_pending_language_passes([source.id for source in sources]))

    @staticmethod
    def merge_page(
        existing_text: str,
        existing_confidence: float,
        lines: list[tuple[str, float]],
        language: OcrComponentInfo,
    ) -> tuple[str, float, list[float]]:
        """Add the lines `language` read believably to a page's text.

        Returns the merged text, the page's new confidence (the average over its lines, so the
        lines added count in proportion to how many it already had, as for deeper phases) and the
        scores of the lines that were added.
        """
        kept = LanguageDetector.believable_lines(tuple(lines), language)
        merged, added = Deepening.merge_lines(existing_text, [text for text, _ in kept])
        added_scores = [kept[i][1] for i in added]
        confidence = existing_confidence
        if added_scores:
            existing_lines = sum(1 for line in existing_text.split("\n") if line.strip())
            confidence = (existing_confidence * existing_lines + sum(added_scores)) / (
                existing_lines + len(added_scores)
            )
        return merged, confidence, added_scores

    @staticmethod
    def dominant_language(text: str, language_ids: list[str]) -> str | None:
        """Of `language_ids`, the one whose script has the most characters in `text`."""
        counts = Scripts.counts(text)
        best: tuple[int, str] | None = None
        for language_id in language_ids:
            info = OcrCatalog.language(language_id)
            if info is None:
                continue
            candidate = (counts.get(info.script, 0), language_id)
            if best is None or candidate[0] > best[0]:
                best = candidate
        return best[1] if best is not None and best[0] > 0 else None

    @staticmethod
    def _page_languages(row: Row, language_id: str, added: bool, merged: str) -> tuple[str, str]:
        """`(language, ocr_langs)` to store for a page after a pass: the languages that
        contributed to it, and the one most of its text is in."""
        langs = [part for part in (row["ocr_langs"] or "").split(",") if part]
        if not langs and row["language"]:
            langs = [row["language"]]
        if added and language_id not in langs:
            langs.append(language_id)
        # Only languages whose script is actually in the text contributed to it: a first read
        # that was all made-up characters, and so dropped, does not count.
        present = Scripts.present(merged)
        contributed = [
            lang_id
            for lang_id in langs
            if (info := OcrCatalog.language(lang_id)) is not None and info.script in present
        ]
        langs = contributed or langs
        primary = LanguagePasses.dominant_language(merged, langs) or row["language"] or language_id
        return primary, ",".join(langs)

    @staticmethod
    def process_unit(
        storage: Storage, unit: LanguageUnit, *, db_lock: threading.Lock | None = None
    ) -> bool:
        """Read `unit`'s file in the pass's language and merge the result into its stored pages.

        Returns whether the pass succeeded; a failure is recorded on the pass (status `error`
        and its message) and leaves the pages as they were. The file is read and OCR'd without
        `db_lock` held; every database access goes through it.
        """
        lock = db_lock or contextlib.nullcontext()
        info = OcrCatalog.language(unit.language)
        started = datetime.now(UTC).isoformat()
        with lock:
            storage.update_document_language(
                unit.document_id, unit.language, LanguagePlan.PROCESSING, None, None, started, None
            )
            storage.commit()
        try:
            if info is None:
                raise ValueError(f"unknown language {unit.language!r}")
            with lock:
                stored = {
                    row["page_number"]: row
                    for row in storage.list_ocr_document_pages(unit.table, unit.document_id)
                }
            if not stored:
                raise ValueError("the file has no stored pages to read")
            engine_language = Quick.engine_language(unit.language)
            reader = Readers.for_path(unit.file_path)
            all_scores: list[float] = []
            page_scores: list[float] = []  # one per page the pass added text to
            _logger.info(
                "Language pass: file=%s language=%s position=%d",
                unit.file_path,
                unit.language,
                unit.position,
            )
            for page_number, page in enumerate(reader.read(unit.file_path), start=1):
                row = stored.get(page_number)
                if row is None or row["source"] == "native":
                    continue
                result = PageOcr.ocr_page(storage, page, engine_language)
                lines = list(result.lines) or [
                    (text, result.confidence) for text in result.text.split("\n") if text.strip()
                ]
                with lock:
                    current = storage.get_ocr_page_text_row(unit.table, row["id"])
                    if current is None:  # the file was replaced or removed while this ran
                        raise FileNotFoundError(unit.file_path)
                    merged, confidence, added_scores = LanguagePasses.merge_page(
                        current["ocr_text"], current["confidence"], lines, info
                    )
                    all_scores.extend(added_scores)
                    if added_scores:
                        page_scores.append(sum(added_scores) / len(added_scores))
                    if added_scores:
                        storage.update_ocr_page_text(
                            unit.table,
                            row["id"],
                            merged,
                            confidence,
                            current["ocr_phase"],
                            current["ocr_angles"],
                        )
                    language, ocr_langs = LanguagePasses._page_languages(
                        row, unit.language, bool(added_scores), merged
                    )
                    storage.update_ocr_page_languages(unit.table, row["id"], language, ocr_langs)
                    storage.commit()
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't stop the queue
            _logger.error(
                "Language pass failed: file=%s language=%s error=%s: %s",
                unit.file_path,
                unit.language,
                type(exc).__name__,
                exc,
            )
            with lock:
                storage.update_document_language(
                    unit.document_id,
                    unit.language,
                    LanguagePlan.ERROR,
                    None,
                    str(exc),
                    None,
                    datetime.now(UTC).isoformat(),
                )
                storage.commit()
            return False

        mean = sum(all_scores) / len(all_scores) if all_scores else None
        with lock:
            # The pass's own confidence goes to its language's statistics (not the first read's).
            Metrics.fold_confidence(
                storage,
                unit.file_type,
                Extensions.of(unit.file_path),
                PageStorage.DEFAULT_PROCESS_TYPE,
                unit.language,
                page_scores,
            )
            storage.update_document_language(
                unit.document_id,
                unit.language,
                LanguagePlan.DONE,
                mean,
                None,
                None,
                datetime.now(UTC).isoformat(),
            )
            storage.commit()
        return True

    @staticmethod
    def run_batch(
        storage: Storage,
        sources: list[Source],
        *,
        should_stop: Callable[[], bool] | None = None,
        has_quick_work: Callable[[], bool] | None = None,
        skip_units: set[tuple[int, str]] | None = None,
        on_unit_start: Callable[[str, str], None] | None = None,
        on_unit_done: Callable[[str], None] | None = None,
    ) -> int:
        """Run the next round of queued language passes over `sources`' indexed files.

        Takes each file's next pending pass in queue order (so every file gets its second
        language before any gets its third) and stops early - between passes - when `should_stop`
        returns True or `has_quick_work` reports files waiting for their first pass; the caller
        handles those and calls this again. A pass that fails is added to `skip_units` (pass the
        same set across calls) so it is not retried forever.

        `on_unit_start(path, language)` / `on_unit_done(path)` bracket each pass. Returns how
        many passes were attempted - 0 means nothing was waiting.
        """
        skip = skip_units if skip_units is not None else set()
        units = LanguagePasses.find_units(storage, sources, skip)
        done = 0
        last_quick_check = time.monotonic()
        for unit in units:
            if should_stop is not None and should_stop():
                break
            # Looking for new files scans the sources, so it is not done for every pass.
            if (
                has_quick_work is not None
                and time.monotonic() - last_quick_check >= Deepening.QUICK_WORK_CHECK_SECONDS
            ):
                last_quick_check = time.monotonic()
                if has_quick_work():
                    break
            if on_unit_start is not None:
                on_unit_start(str(unit.file_path), unit.language)
            if not LanguagePasses.process_unit(storage, unit):
                skip.add(unit.key)
            done += 1
            if on_unit_done is not None:
                on_unit_done(str(unit.file_path))
        return done
