"""The job protocol, version 1: the manifest the client sends and the result the worker returns.

Changes within v1 are additive: readers ignore fields they don't know. Another major version is
refused (`unsupported_protocol`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import jsonschema

from vethuq_worker.errors import JobError

PROTOCOL = 1
MAX_PAGES = 200
MAX_BYTES = 200 * 1024 * 1024


def schema(name: str) -> dict[str, Any]:
    """`manifest` or `result`."""
    text = resources.files("vethuq_worker").joinpath(f"schemas/{name}.schema.json").read_text()
    return json.loads(text)


def validate(name: str, document: Any) -> None:
    """Raise `JobError` if `document` isn't a valid manifest/result of this protocol."""
    if isinstance(document, dict) and document.get("protocol") not in (None, PROTOCOL):
        raise JobError(
            "unsupported_protocol", f"Protocol {document.get('protocol')!r} isn't supported."
        )
    code = "bad_manifest" if name == "manifest" else "bad_result"
    try:
        jsonschema.validate(document, schema(name))
    except jsonschema.ValidationError as error:
        where = "/".join(str(part) for part in error.absolute_path) or "document"
        raise JobError(code, f"Invalid {name} at {where}: {error.message}") from None


@dataclass(frozen=True)
class PageSpec:
    key: str
    file: str
    language: str
    phase: str = "quick"
    size_factor: float = 1.0


@dataclass(frozen=True)
class Manifest:
    job_id: str
    pages: tuple[PageSpec, ...]
    max_pages: int = MAX_PAGES
    max_bytes: int = MAX_BYTES
    addon_settings: dict[str, dict[str, str]] = field(default_factory=dict)
    created: str = ""
    client: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "job_id": self.job_id,
            "created": self.created,
            "client": self.client,
            "limits": {"max_pages": self.max_pages, "max_bytes": self.max_bytes},
            "addon_settings": self.addon_settings,
            "pages": [
                {
                    "key": p.key,
                    "file": p.file,
                    "language": p.language,
                    "phase": p.phase,
                    "size_factor": p.size_factor,
                }
                for p in self.pages
            ],
        }

    @staticmethod
    def from_dict(document: Any) -> Manifest:
        validate("manifest", document)
        return Manifest(
            job_id=document["job_id"],
            pages=tuple(
                PageSpec(
                    p["key"],
                    p["file"],
                    p["language"],
                    p.get("phase", "quick"),
                    float(p.get("size_factor", 1.0)),
                )
                for p in document["pages"]
            ),
            max_pages=document["limits"]["max_pages"],
            max_bytes=document["limits"]["max_bytes"],
            addon_settings=document.get("addon_settings", {}),
            created=document.get("created", ""),
            client=document.get("client", ""),
        )


@dataclass(frozen=True)
class PageResult:
    key: str
    ok: bool
    text: str = ""
    confidence: float = 0.0
    engine: str = ""
    language: str = ""
    image_width: int | None = None
    image_height: int | None = None
    lines: tuple[tuple[str, float], ...] = ()
    seconds: float = 0.0
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"key": self.key, "ok": self.ok, "seconds": self.seconds}
        if self.ok:
            document.update(
                text=self.text,
                confidence=self.confidence,
                engine=self.engine,
                language=self.language,
                image_width=self.image_width,
                image_height=self.image_height,
                lines=[[text, conf] for text, conf in self.lines],
            )
        else:
            document["error"] = {"code": self.error_code, "message": self.error_message}
        return document

    @staticmethod
    def from_dict(document: dict[str, Any]) -> PageResult:
        error = document.get("error") or {}
        return PageResult(
            key=document["key"],
            ok=document["ok"],
            text=document.get("text", ""),
            confidence=float(document.get("confidence", 0.0)),
            engine=document.get("engine", ""),
            language=document.get("language", ""),
            image_width=document.get("image_width"),
            image_height=document.get("image_height"),
            lines=tuple((str(t), float(c)) for t, c in document.get("lines", [])),
            seconds=float(document.get("seconds", 0.0)),
            error_code=error.get("code", ""),
            error_message=error.get("message", ""),
        )


@dataclass(frozen=True)
class JobResult:
    job_id: str
    status: str  # done | partial | failed
    pages: tuple[PageResult, ...] = ()
    billable_seconds: float = 0.0
    worker: str = ""
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "protocol": PROTOCOL,
            "job_id": self.job_id,
            "status": self.status,
            "worker": self.worker,
            "billable_seconds": self.billable_seconds,
            "pages": [p.to_dict() for p in self.pages],
        }
        if self.error_code:
            document["error"] = {"code": self.error_code, "message": self.error_message}
        return document

    @staticmethod
    def from_dict(document: Any) -> JobResult:
        validate("result", document)
        error = document.get("error") or {}
        return JobResult(
            job_id=document["job_id"],
            status=document["status"],
            pages=tuple(PageResult.from_dict(p) for p in document["pages"]),
            billable_seconds=float(document.get("billable_seconds", 0.0)),
            worker=document.get("worker", ""),
            error_code=error.get("code", ""),
            error_message=error.get("message", ""),
        )
