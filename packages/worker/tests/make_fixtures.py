"""Regenerates the synthetic fixtures in github/protocol/v1 (`uv run python make_fixtures.py`).

The key is public and the pages are blank: the fixtures only exist so every implementation of
the protocol can check that it opens what another one sealed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy

from vethuq_addon_api import LanguageSpec, OcrRequest
from vethuq_addon_api.testing import FakeExecutor
from vethuq_worker import JobBuilder, StaticEngine, run_job, using

ROOT = Path(__file__).resolve().parents[3] / "github" / "protocol" / "v1"
KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
JOB_ID = "fixture-job-0001"
EN = LanguageSpec("en", "English", default=True)


def main() -> None:
    builder = JobBuilder(KEY, job_id=JOB_ID, client="fixture")
    for index in (1, 2):
        image = numpy.full((16, 24, 3), 255 - index, dtype=numpy.uint8)
        builder.add(OcrRequest(f"d1.l1.{index}:0", image, EN, size_factor=1.0))
    payload = ROOT / "fixtures" / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    (payload / "payload.bin").write_bytes(builder.build())
    manifest = builder.manifest().to_dict()
    manifest["created"] = "2026-01-01T00:00:00+00:00"
    (ROOT / "examples" / "manifest.example.json").write_text(json.dumps(manifest, indent=2) + "\n")
    executor = FakeExecutor({"d1.l1.1:0": "Hello world", "d1.l1.2:0": "Second page"})
    result = run_job(
        JOB_ID, payload, ROOT / "fixtures" / "out", KEY, using(StaticEngine(executor, [EN]))
    )
    document = result.to_dict()
    document["billable_seconds"] = 0.1
    for page in document["pages"]:
        page["seconds"] = 0.05
    (ROOT / "examples" / "result.example.json").write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
