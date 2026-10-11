"""The VethuQ job protocol (v1) and the worker that reads a job's pages."""

from vethuq_worker.client import JobBuilder, open_result, to_ocr_results
from vethuq_worker.crypto import generate_key
from vethuq_worker.errors import JobError
from vethuq_worker.protocol import JobResult, Manifest, PageResult, PageSpec
from vethuq_worker.worker import Engine, StaticEngine, run_job, using

__all__ = [
    "Engine",
    "JobBuilder",
    "JobError",
    "JobResult",
    "Manifest",
    "PageResult",
    "PageSpec",
    "StaticEngine",
    "generate_key",
    "open_result",
    "run_job",
    "to_ocr_results",
    "using",
]
