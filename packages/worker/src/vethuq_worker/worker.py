"""The worker: reads a sealed job and writes a sealed result.

Nothing leaves the job: no file name, page text or image is logged, and the only output is the
sealed result file. The worker enforces the protocol's caps whatever the manifest claims, and
add-ons enforce their own licences when the engine is built (a page whose language or engine
isn't available fails with its own error; it doesn't stop the job).
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from vethuq_addon_api import LanguageSpec, OcrExecutor, OcrRequest
from vethuq_worker import container, crypto, images
from vethuq_worker.client import PAYLOAD, RESULT
from vethuq_worker.errors import JobError
from vethuq_worker.protocol import MAX_BYTES, MAX_PAGES, JobResult, Manifest, PageResult

RESULT_FILE = "result.bin"
PAYLOAD_FILE = "payload.bin"
logger = logging.getLogger("vethuq.worker")


def worker_version() -> str:
    try:
        from importlib.metadata import version

        return f"vethuq-worker {version('vethuq-worker')}"
    except Exception:  # noqa: BLE001 - a missing version never blocks a job
        return "vethuq-worker"


class Engine(ABC):
    """What the worker reads with: an executor and the languages it can read."""

    @abstractmethod
    def language(self, language_id: str) -> LanguageSpec | None:
        """The language if it can be used now, else None."""

    @property
    @abstractmethod
    def executor(self) -> OcrExecutor: ...


class StaticEngine(Engine):
    """An engine over a given executor and languages (tests, or other hosts)."""

    def __init__(self, executor: OcrExecutor, languages: list[LanguageSpec]) -> None:
        self._executor = executor
        self._languages = {spec.id: spec for spec in languages if spec.available}

    def language(self, language_id: str) -> LanguageSpec | None:
        return self._languages.get(language_id)

    @property
    def executor(self) -> OcrExecutor:
        return self._executor


class CoreEngine(Engine):
    """VethuQ's own local OCR over the installed add-ons, with the manifest's add-on settings
    (licence tokens) applied to a throwaway database. Needs the `run` extra."""

    def __init__(self, manifest: Manifest, workdir: Path, models: Path | None = None) -> None:
        from vethuq import VethuQ
        from vethuq._addons.settings import _AddonSettingsStore
        from vethuq._tiers.local import _LocalExecutor

        (workdir / "db").mkdir(parents=True, exist_ok=True)
        db_path = workdir / "db" / "vethuq.db"
        if models is not None and not (workdir / "models").exists():
            (workdir / "models").symlink_to(models, target_is_directory=True)
        self._client = VethuQ(db_path)
        self._client._open_database()  # creates the settings table before add-ons read it
        for addon_id, values in manifest.addon_settings.items():
            store = _AddonSettingsStore(db_path, addon_id)
            for key, value in values.items():
                store.set(key, value)
        self._executor = _LocalExecutor(self._client._runtime())

    def language(self, language_id: str) -> LanguageSpec | None:
        for spec in self._client._manager().language_specs():
            if spec.id == language_id:
                return spec if spec.available else None
        return None

    @property
    def executor(self) -> OcrExecutor:
        return self._executor

    def close(self) -> None:
        self._client.close()


def using(engine: Engine):
    """An `engine_for` that always gives `engine` (tests, other hosts)."""

    @contextmanager
    def engine_for(manifest: Manifest) -> Iterator[Engine]:
        yield engine

    return engine_for


@contextmanager
def core_engine(manifest: Manifest) -> Iterator[CoreEngine]:
    models = os.environ.get("VETHUQ_MODELS")
    with tempfile.TemporaryDirectory(prefix="vethuq-job-") as folder:
        engine = CoreEngine(manifest, Path(folder), Path(models) if models else None)
        try:
            yield engine
        finally:
            engine.close()


def _failed(job_id: str, code: str, message: str) -> JobResult:
    return JobResult(
        job_id, "failed", worker=worker_version(), error_code=code, error_message=message
    )


def _read_pages(manifest: Manifest, files: dict[str, bytes], engine: Engine) -> JobResult:
    results: list[PageResult] = []
    started = time.monotonic()
    for page in manifest.pages:
        began = time.monotonic()
        spec = engine.language(page.language)
        if spec is None:
            results.append(
                PageResult(
                    page.key,
                    False,
                    error_code="language_unavailable",
                    error_message=f"Language {page.language!r} isn't available on the worker.",
                )
            )
            continue
        data = files.get(page.file)
        if data is None:
            results.append(
                PageResult(
                    page.key,
                    False,
                    error_code="missing_image",
                    error_message="The page's image is missing.",
                )
            )
            continue
        try:
            outcome = engine.executor.recognize(
                OcrRequest(page.key, images.from_png(data), spec, page.phase, page.size_factor)
            )
        except Exception as error:  # noqa: BLE001 - one page never stops the job
            # Only the exception's type is reported: its message could carry page text.
            logger.warning("a page could not be read (%s)", type(error).__name__)
            results.append(
                PageResult(
                    page.key,
                    False,
                    seconds=time.monotonic() - began,
                    error_code="ocr_failed",
                    error_message=f"The page could not be read ({type(error).__name__}).",
                )
            )
            continue
        results.append(
            PageResult(
                page.key,
                True,
                text=outcome.text,
                confidence=outcome.confidence,
                engine=outcome.engine,
                language=outcome.language,
                image_width=outcome.image_width,
                image_height=outcome.image_height,
                lines=outcome.lines,
                seconds=time.monotonic() - began,
            )
        )
    good = sum(1 for page in results if page.ok)
    status = "done" if good == len(results) else ("partial" if good else "failed")
    return JobResult(
        manifest.job_id,
        status,
        tuple(results),
        billable_seconds=math.ceil((time.monotonic() - started) * 10) / 10,
        worker=worker_version(),
    )


def process(job_id: str, master_key: str, blob: bytes, engine_for) -> JobResult:
    """Read a sealed payload. `engine_for(manifest)` is a context manager giving the `Engine`.

    Raises `JobError` only for what makes the job unreadable; everything else is in the result.
    """
    if len(blob) > MAX_BYTES + 1024 * 1024:
        raise JobError("too_large", "The payload is larger than a job may be.")
    plain = crypto.open_sealed(master_key, PAYLOAD, job_id, blob)
    entries = container.unpack(plain, max_bytes=MAX_BYTES)
    if "manifest.json" not in entries:
        raise JobError("bad_payload", "The job has no manifest.")
    try:
        document = json.loads(entries.pop("manifest.json"))
    except ValueError:
        raise JobError("bad_manifest", "The manifest isn't valid JSON.") from None
    manifest = Manifest.from_dict(document)
    if manifest.job_id != job_id:
        raise JobError("bad_manifest", "The manifest belongs to another job.")
    if len(manifest.pages) > min(manifest.max_pages, MAX_PAGES):
        raise JobError("too_many_pages", f"A job holds at most {MAX_PAGES} pages.")
    if sum(len(data) for data in entries.values()) > min(manifest.max_bytes, MAX_BYTES):
        raise JobError("too_large", "The job is larger than a job may be.")
    with engine_for(manifest) as engine:
        return _read_pages(manifest, entries, engine)


def run_job(
    job_id: str,
    payload: Path,
    out: Path,
    master_key: str,
    engine_for=None,
) -> JobResult:
    """Read the job in `payload` (a folder holding `payload.bin`) and write `out/result.bin`.

    Any job whose key and id are right gets a sealed result, even a failed one, so the client
    learns why. Only a wrong key or id can't be answered (nothing can be sealed for them).
    """
    crypto.decode_key(master_key)
    engine_for = engine_for or core_engine
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = process(job_id, master_key, (payload / PAYLOAD_FILE).read_bytes(), engine_for)
    except JobError as error:
        result = _failed(job_id, error.code, error.message)
    except OSError:
        result = _failed(job_id, "bad_payload", "The payload can't be read.")
    (out / RESULT_FILE).write_bytes(
        crypto.seal(master_key, RESULT, job_id, json.dumps(result.to_dict()).encode())
    )
    return result
