"""The deeper OCR phases: re-reading already-indexed pages at rotated angles."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil

if TYPE_CHECKING:
    import numpy as np

from vethuq_core.logs import Logs
from vethuq_core.ocr.engines import Engines
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.ocr.scheduler import Scheduler
from vethuq_core.readers import Readers
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Source
from vethuq_core.storage import Storage

_logger = Logs.get_logger("index")


@dataclass(frozen=True)
class DeepenUnit:
    """One page that still needs `phase`'s angles read and merged in."""

    table: str  # 'pdf_pages' | 'image_pages'
    page_id: int
    document_id: int  # the `document_index` row holding the page
    logical_document_id: int  # its `documents` row, which phase progress is tracked on
    file_path: Path
    file_type: str
    page_number: int
    page_source: str  # 'ocr' | 'mixed'
    phase: int
    angles_done: frozenset[int]

    @property
    def key(self) -> tuple[str, int]:
        return self.table, self.page_id


class Deepening:
    # OCR runs in phases so a file is searchable after one quick pass while the
    # slower rotated-text passes continue in the background. Each phase reads a
    # page at these angles (degrees, counter-clockwise) and adds whatever text it
    # finds to what earlier phases already found. The `index_engine` setting picks
    # how far to go (see `Deepening.ENGINE_PHASES`).
    PHASE_ANGLES: dict[int, tuple[int, ...]] = {
        1: (0,),
        2: (90, 180, 270),
        3: tuple(angle for angle in range(15, 360, 15) if angle % 90),
    }
    ENGINE_PHASES = {"quick": 1, "moderate": 2, "deep": 3}
    PHASE_NAMES = {phase: name for name, phase in ENGINE_PHASES.items()}

    # A line found on a rotated pass must be at least this confident to be kept -
    # odd angles read drawing strokes and noise as text far more often than upright
    # text does, and that shouldn't pollute the searchable text.
    MIN_ROTATED_LINE_SCORE = 0.5

    # How often (seconds) deeper phases re-check for new files that should jump the queue.
    QUICK_WORK_CHECK_SECONDS = 5.0

    @staticmethod
    def max_phase(storage: Storage) -> int:
        """The highest phase the `index_engine` setting asks for (1 = quick only)."""
        return Deepening.ENGINE_PHASES.get(OcrSettings.get_engine(storage), 1)

    @staticmethod
    def parse_angles(value: str) -> set[int]:
        return {int(part) for part in value.split(",") if part.strip()}

    @staticmethod
    def format_angles(angles: Collection[int]) -> str:
        return ",".join(str(angle) for angle in sorted(angles))

    @staticmethod
    def completed_phase(done_angles: Collection[int]) -> int:
        """Highest phase whose angles have all been read (phases complete in order)."""
        done = set(done_angles)
        completed = 0
        for phase in sorted(Deepening.PHASE_ANGLES):
            if not set(Deepening.PHASE_ANGLES[phase]) <= done:
                break
            completed = phase
        return completed

    @staticmethod
    def normalize_line(line: str) -> str:
        return " ".join(line.casefold().split())

    @staticmethod
    def merge_lines(existing_text: str, new_lines: list[str]) -> tuple[str, list[int]]:
        """Add `new_lines` to `existing_text`, skipping what it already says.

        A new line already contained in an existing one is dropped; an existing
        line contained in a new (longer) one is replaced by it, so a word read
        partially on one angle and fully on another ends up once, as the full
        word. Returns the merged text and the indexes into `new_lines` of the
        lines that were added.
        """
        lines = existing_text.split("\n") if existing_text else []
        normalized = [Deepening.normalize_line(line) for line in lines]
        added: list[int] = []
        for index, line in enumerate(new_lines):
            new = Deepening.normalize_line(line)
            if not new or any(new in existing for existing in normalized):
                continue
            keep = [i for i, existing in enumerate(normalized) if existing and existing not in new]
            lines = [lines[i] for i in keep]
            normalized = [normalized[i] for i in keep]
            lines.append(line.strip())
            normalized.append(new)
            added.append(index)
        return "\n".join(lines), added

    @staticmethod
    def rotate_array(array: np.ndarray, angle: int) -> np.ndarray:
        """Rotate `array` counter-clockwise by `angle` degrees, growing the canvas to fit."""
        import cv2

        angle %= 360
        if angle == 0:
            return array
        # Right angles are exact pixel moves - no interpolation, no blank corners.
        exact = {
            90: cv2.ROTATE_90_COUNTERCLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_CLOCKWISE,
        }
        if angle in exact:
            return cv2.rotate(array, exact[angle])

        height, width = array.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        new_width = int(height * sin + width * cos)
        new_height = int(height * cos + width * sin)
        matrix[0, 2] += new_width / 2 - width / 2
        matrix[1, 2] += new_height / 2 - height / 2
        return cv2.warpAffine(array, matrix, (new_width, new_height), borderValue=(255, 255, 255))

    @staticmethod
    def read_image_array(file_path: Path) -> np.ndarray:
        import cv2
        import numpy as np

        # imdecode over fromfile, not cv2.imread: imread can't open non-ASCII paths on Windows.
        array = cv2.imdecode(np.fromfile(file_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if array is None:
            raise ValueError(f"could not decode image: {file_path}")
        return array

    @staticmethod
    def read_at_angle(
        storage: Storage, arrays: list[np.ndarray], angle: int
    ) -> tuple[list[str], list[float]]:
        """OCR each of `arrays` rotated by `angle`; return its confident lines and their scores."""
        engine = Engines.get(storage)
        texts: list[str] = []
        scores: list[float] = []
        for array in arrays:
            result = engine.recognize(Deepening.rotate_array(array, angle))
            for text, score in result.lines:
                if score >= Deepening.MIN_ROTATED_LINE_SCORE and text.strip():
                    texts.append(text)
                    scores.append(score)
        return texts, scores

    @staticmethod
    def find_units(
        storage: Storage,
        sources: list[Source],
        max_phase: int,
        skip: Collection[tuple[str, int]] = (),
    ) -> list[DeepenUnit]:
        """Pages under `sources` still short of `max_phase`, lowest next phase first.

        Ordering by next phase is what makes every page get its moderate pass
        before any page gets a deep one, rather than finishing one document's
        deep pass while another still has only its quick one. Duplicates (which
        reuse their original's pages) and native-text pages (nothing to OCR) are
        left out.
        """
        if max_phase <= 1 or not sources:
            return []
        source_ids = [source.id for source in sources]
        units: list[DeepenUnit] = []
        for table, file_type in (("pdf_pages", "pdf"), ("image_pages", "image")):
            for row in storage.list_ocr_pages_short_of_phase(table, max_phase, source_ids):
                unit = DeepenUnit(
                    table=table,
                    page_id=row["id"],
                    document_id=row["document_id"],
                    logical_document_id=row["logical_document_id"],
                    file_path=Path(row["file_path"]),
                    file_type=file_type,
                    page_number=row["page_number"],
                    page_source=row["page_source"],
                    phase=row["ocr_phase"] + 1,
                    angles_done=frozenset(Deepening.parse_angles(row["ocr_angles"])),
                )
                if unit.key not in skip:
                    units.append(unit)
        units.sort(key=lambda unit: (unit.phase, unit.document_id, unit.page_number))
        return units

    @staticmethod
    def render_unit_arrays(unit: DeepenUnit) -> list[np.ndarray]:
        """The image(s) a page's OCR reads: the file itself, the rendered PDF page, or
        (for a mixed page, whose text layer is already read natively) just its image regions."""
        if unit.file_type == "image":
            return [Deepening.read_image_array(unit.file_path)]
        reader = Readers.for_file_type(unit.file_type)
        for page in reader.read(unit.file_path, unit.page_number):
            if unit.page_source == "mixed":
                return [cast("np.ndarray", page.render(region)) for region in page.image_regions]
            return [cast("np.ndarray", page.render(None))]
        raise ValueError(f"page {unit.page_number} not found: {unit.file_path}")

    @staticmethod
    def start_document_phase(storage: Storage, unit: DeepenUnit) -> None:
        """Record that real work on `unit`'s document for `unit.phase` has begun (once)."""
        storage.start_ocr_document_phase(
            unit.logical_document_id, unit.phase, datetime.now(UTC).isoformat()
        )

    @staticmethod
    def add_document_phase_work(
        storage: Storage,
        unit: DeepenUnit,
        seconds: float,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> None:
        """Accumulate time/memory/cpu spent on `unit`'s document for `unit.phase`.

        Time is active OCR time summed across every page (and every run that
        worked on the document), never wall-clock - a pause, or giving way to a
        new file, would otherwise make a phase look far slower than it is.
        """
        row = storage.get_ocr_document_phase_work(unit.logical_document_id, unit.phase)
        if row is None:
            return
        total = row["duration_seconds"] + seconds
        cpu = cpu_percent
        if row["cpu_percent"] is not None and total > 0:
            cpu = (row["cpu_percent"] * row["duration_seconds"] + cpu_percent * seconds) / total
        storage.update_ocr_document_phase_work(
            unit.logical_document_id,
            unit.phase,
            total,
            max(row["peak_memory_mb"] or 0.0, peak_memory_mb),
            cpu,
        )

    @staticmethod
    def complete_document_phase_if_done(storage: Storage, unit: DeepenUnit) -> None:
        """Mark `unit`'s document finished for `unit.phase` once every page has reached it.

        Sets `completed_at`/`indexed_at` (the moment the last page's text for this
        phase became searchable) and folds the document's accumulated work into
        that phase's `processing_metrics`. A document is only ever folded once.
        """
        if storage.count_ocr_pages_short_of_phase(unit.table, unit.document_id, unit.phase):
            return
        row = storage.get_ocr_document_phase_completion(unit.logical_document_id, unit.phase)
        if row is None or row["completed_at"] is not None:
            return
        now = datetime.now(UTC).isoformat()
        storage.complete_ocr_document_phase(unit.logical_document_id, unit.phase, now)
        if row["duration_seconds"] <= 0:
            return
        doc = storage.get_ocr_document_file_size(unit.document_id)
        Metrics.fold_processing(
            storage,
            phase=unit.phase,
            file_type=unit.file_type,
            file_size_bytes=(doc["file_size_bytes"] if doc is not None else 0) or 0,
            duration=row["duration_seconds"],
            peak_memory_mb=row["peak_memory_mb"] or 0.0,
            cpu_percent=row["cpu_percent"] or 0.0,
        )

    @staticmethod
    def deepen_unit(
        storage: Storage,
        unit: DeepenUnit,
        *,
        db_lock: threading.Lock,
        should_yield: Callable[[], bool],
    ) -> int:
        """Read `unit`'s page at its phase's remaining angles, merging each result in.

        Every angle's text is saved as soon as it's read, so giving up part-way
        (`should_yield` returns True - a stop request, or new files that should be
        indexed first) loses nothing and the next run carries on from the next
        angle. The time spent is added to the document's `document_phases` row as
        it goes, and once the document's last page reaches the phase that row is
        completed and folded into `processing_metrics`. Returns how many angle
        passes completed.
        """
        todo = [
            angle for angle in Deepening.PHASE_ANGLES[unit.phase] if angle not in unit.angles_done
        ]
        if not todo:
            # Angles already all read (e.g. an earlier run was interrupted right at the end)
            # - just record the phase as done so it isn't picked up again.
            with db_lock:
                storage.mark_ocr_page_phase_done(unit.table, unit.phase, unit.page_id)
                Deepening.complete_document_phase_if_done(storage, unit)
                storage.commit()
            return 1

        process = psutil.Process()
        process.cpu_percent(interval=None)  # prime; the next call reports usage since now
        peak_rss = process.memory_info().rss
        started = time.perf_counter()
        not_working = 0.0  # time in `should_yield` (a pause, a scan for new files) - not OCR work
        tracked = False
        passes = 0
        try:
            arrays = Deepening.render_unit_arrays(unit)
            for angle in todo:
                waited_from = time.perf_counter()
                give_way = should_yield()
                not_working += time.perf_counter() - waited_from
                if give_way:
                    break
                if not tracked:
                    with db_lock:
                        Deepening.start_document_phase(storage, unit)
                        storage.commit()
                    tracked = True
                texts, scores = Deepening.read_at_angle(storage, arrays, angle)
                peak_rss = max(peak_rss, process.memory_info().rss)
                with db_lock:
                    row = storage.get_ocr_page_text_row(unit.table, unit.page_id)
                    if row is None:  # the document was replaced/removed while this was running
                        return passes
                    existing_lines = sum(1 for line in row["ocr_text"].split("\n") if line.strip())
                    merged, added = Deepening.merge_lines(row["ocr_text"], texts)
                    done = Deepening.parse_angles(row["ocr_angles"]) | {angle}
                    # Confidence is the average over the page's lines, so lines this pass
                    # added count in proportion to how many lines the page already had.
                    confidence = row["confidence"]
                    added_scores = [scores[i] for i in added]
                    if added_scores:
                        confidence = (confidence * existing_lines + sum(added_scores)) / (
                            existing_lines + len(added_scores)
                        )
                    storage.update_ocr_page_text(
                        unit.table,
                        unit.page_id,
                        merged,
                        confidence,
                        max(row["ocr_phase"], Deepening.completed_phase(done)),
                        Deepening.format_angles(done),
                    )
                    storage.commit()
                passes += 1
        finally:
            if tracked:
                # Recorded even when interrupted or failed - the work was still done.
                elapsed = max(0.0, time.perf_counter() - started - not_working)
                cpu_percent = process.cpu_percent(interval=None)
                with db_lock:
                    Deepening.add_document_phase_work(
                        storage, unit, elapsed, max(peak_rss, 0) / (1024 * 1024), cpu_percent
                    )
                    storage.commit()

        if passes == len(todo):
            with db_lock:
                Deepening.complete_document_phase_if_done(storage, unit)
                storage.commit()
        return passes

    @staticmethod
    def run_batch(
        storage: Storage,
        sources: list[Source],
        *,
        max_phase: int,
        should_stop: Callable[[], bool] | None = None,
        has_quick_work: Callable[[], bool] | None = None,
        skip_units: set[tuple[str, int]] | None = None,
        on_unit_start: Callable[[str, int], None] | None = None,
        on_unit_done: Callable[[str], None] | None = None,
    ) -> int:
        """Run the next round of deeper-phase work over `sources`' indexed pages.

        Processes every page still short of `max_phase`, lowest next phase first,
        with the worker count the `thread_workers` setting resolves to. It stops
        early - after the angle pass in flight, never mid-pass - when `should_stop`
        returns True, or when `has_quick_work` reports new files waiting for their
        quick pass; the caller is expected to handle those and call this again.
        `has_quick_work` is only re-checked every `Deepening.QUICK_WORK_CHECK_SECONDS`, and
        is called with the batch's DB lock held.

        A page whose deeper read fails (e.g. its file vanished) is added to
        `skip_units` - pass the same set across calls so it isn't retried forever.
        `on_unit_start(path, phase)`/`on_unit_done(path)` bracket each page.

        Returns the number of angle passes completed - 0 means nothing was left
        to do (or nothing could be done).
        """
        skip = skip_units if skip_units is not None else set()
        units = Deepening.find_units(storage, sources, max_phase, skip)
        if not units:
            return 0

        type_counts = Readers.new_file_type_counts()
        for unit in units:
            type_counts[unit.file_type] += 1
        workers = max(1, Scheduler.resolve_workers(storage, type_counts))

        halted = threading.Event()
        coord_lock = threading.Lock()
        db_lock = threading.Lock()
        next_index = 0
        passes_total = 0
        last_quick_check = time.monotonic()

        def should_yield() -> bool:
            nonlocal last_quick_check
            if halted.is_set():
                return True
            if should_stop is not None and should_stop():
                halted.set()
                return True
            if has_quick_work is None:
                return False
            with coord_lock:
                now = time.monotonic()
                if now - last_quick_check < Deepening.QUICK_WORK_CHECK_SECONDS:
                    return False
                last_quick_check = now
            with db_lock:
                if has_quick_work():
                    halted.set()
                    return True
            return False

        def take_next() -> DeepenUnit | None:
            nonlocal next_index
            with coord_lock:
                if halted.is_set() or next_index >= len(units):
                    return None
                unit = units[next_index]
                next_index += 1
                return unit

        def handle_one(unit: DeepenUnit) -> None:
            nonlocal passes_total
            path_str = str(unit.file_path)
            if on_unit_start is not None:
                on_unit_start(path_str, unit.phase)
            passes = 0
            try:
                passes = Deepening.deepen_unit(
                    storage, unit, db_lock=db_lock, should_yield=should_yield
                )
            except Exception:  # noqa: BLE001 - one bad page shouldn't abort the rest
                _logger.warning("Deeper OCR failed for %s", path_str, exc_info=True)
                with coord_lock:
                    skip.add(unit.key)
            finally:
                if on_unit_done is not None:
                    on_unit_done(path_str)
            with coord_lock:
                passes_total += passes

        def worker_loop() -> None:
            while (unit := take_next()) is not None:
                handle_one(unit)

        if workers <= 1:
            worker_loop()
        else:
            threads = [
                threading.Thread(target=worker_loop) for _ in range(min(workers, len(units)))
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        return passes_total

    @staticmethod
    def progress(
        storage: Storage, sources: list[Source], max_phase: int
    ) -> dict[int, tuple[int, int]]:
        """`{phase: (pages done, pages eligible)}` for each deeper phase up to `max_phase`.

        Eligible pages are the ones deeper phases apply to (indexed, not a duplicate,
        not native text); a page is done for a phase once it has completed that phase
        or a later one. Read live from the DB, so it also counts pages finished by
        earlier runs, and is empty when `max_phase` has no deeper phases.
        """
        if max_phase <= 1 or not sources:
            return {}
        source_ids = [source.id for source in sources]
        pages_by_phase: dict[int, int] = {}
        for table in ("pdf_pages", "image_pages"):
            for row in storage.list_ocr_phase_progress_rows(table, source_ids):
                pages_by_phase[row["phase"]] = pages_by_phase.get(row["phase"], 0) + row["pages"]
        total = sum(pages_by_phase.values())
        return {
            phase: (
                sum(n for done_phase, n in pages_by_phase.items() if done_phase >= phase),
                total,
            )
            for phase in range(2, max_phase + 1)
        }

    @staticmethod
    def pending_documents(storage: Storage, sources: list[Source], phase: int) -> dict[str, int]:
        """Count the documents under `sources` with a page still short of `phase`, by file_type.

        This is the unit `processing_metrics` averages a deeper phase over, so
        multiplying it by that phase's average duration estimates the time left
        in it. Always zeros for phase 1 (quick), which is sized by
        `Pending.file_type_counts` instead.
        """
        counts = Readers.new_file_type_counts()
        if phase <= 1 or not sources:
            return counts
        source_ids = [source.id for source in sources]
        for file_type in ("pdf", "image"):
            counts[file_type] = storage.count_ocr_documents_short_of_phase(
                file_type, phase, source_ids
            )
        return counts
