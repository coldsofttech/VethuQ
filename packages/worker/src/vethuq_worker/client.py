"""The client side of the protocol: build a job's payload, read its result."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from vethuq_addon_api import OcrRequest, OcrResult
from vethuq_worker import container, crypto, images
from vethuq_worker.errors import JobError
from vethuq_worker.protocol import (
    MAX_BYTES,
    MAX_PAGES,
    JobResult,
    Manifest,
    PageSpec,
)

PAYLOAD = "payload"
RESULT = "result"


class JobBuilder:
    """Collects the images to read and seals them into one payload.

        builder = JobBuilder(master_key)
        builder.add(request)
        payload = builder.build()   # bytes, ready to upload
        builder.job_id              # name the job

    The caps are checked as pages are added, so a job that would be refused never gets built.
    """

    def __init__(
        self,
        master_key: str,
        *,
        job_id: str | None = None,
        addon_settings: dict[str, dict[str, str]] | None = None,
        max_pages: int = MAX_PAGES,
        max_bytes: int = MAX_BYTES,
        client: str = "",
    ) -> None:
        crypto.decode_key(master_key)
        self._key = master_key
        self.job_id = job_id or secrets.token_urlsafe(12)
        self._addon_settings = addon_settings or {}
        self._max_pages = min(max_pages, MAX_PAGES)
        self._max_bytes = min(max_bytes, MAX_BYTES)
        self._client = client
        self._pages: list[PageSpec] = []
        self._images: dict[str, bytes] = {}
        self._bytes = 0

    def __len__(self) -> int:
        return len(self._pages)

    @property
    def size(self) -> int:
        """The images' size so far, in bytes."""
        return self._bytes

    def fits(self, image_bytes: int = 0) -> bool:
        """Whether one more page of about `image_bytes` still fits."""
        return len(self._pages) < self._max_pages and self._bytes + image_bytes <= self._max_bytes

    def add(self, request: OcrRequest) -> None:
        png = images.to_png(request.image)
        if len(self._pages) >= self._max_pages:
            raise JobError("too_many_pages", f"A job holds at most {self._max_pages} pages.")
        if self._bytes + len(png) > self._max_bytes:
            raise JobError("too_large", "The job would be larger than a job may be.")
        if any(page.key == request.key for page in self._pages):
            raise JobError("bad_manifest", f"Page {request.key!r} is already in the job.")
        name = f"images/{len(self._pages) + 1:04d}.png"
        self._pages.append(
            PageSpec(request.key, name, request.language.id, request.phase, request.size_factor)
        )
        self._images[name] = png
        self._bytes += len(png)

    def manifest(self) -> Manifest:
        return Manifest(
            job_id=self.job_id,
            pages=tuple(self._pages),
            max_pages=self._max_pages,
            max_bytes=self._max_bytes,
            addon_settings=self._addon_settings,
            created=datetime.now(UTC).isoformat(timespec="seconds"),
            client=self._client,
        )

    def build(self) -> bytes:
        if not self._pages:
            raise JobError("bad_manifest", "A job needs at least one page.")
        manifest = self.manifest()
        entries = {"manifest.json": json.dumps(manifest.to_dict()).encode()}
        entries.update(self._images)
        return crypto.seal(self._key, PAYLOAD, self.job_id, container.pack(entries))


def open_result(master_key: str, job_id: str, data: bytes) -> JobResult:
    """Decrypt and check a result file. Raises `JobError` for a result that isn't this job's."""
    try:
        document: Any = json.loads(crypto.open_sealed(master_key, RESULT, job_id, data))
    except ValueError as error:
        raise JobError("bad_result", "The result isn't valid JSON.") from error
    result = JobResult.from_dict(document)
    if result.job_id != job_id:
        raise JobError("bad_result", "The result belongs to another job.")
    return result


def to_ocr_results(result: JobResult) -> dict[str, OcrResult]:
    """The pages that were read, by request key (failed pages are left out)."""
    return {
        page.key: OcrResult(
            text=page.text,
            confidence=page.confidence,
            engine=page.engine,
            language=page.language,
            image_width=page.image_width,
            image_height=page.image_height,
            lines=page.lines,
        )
        for page in result.pages
        if page.ok
    }
