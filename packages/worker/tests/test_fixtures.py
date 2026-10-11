"""The shared fixtures in github/protocol/v1: what any implementation must be able to open."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vethuq_worker import open_result
from vethuq_worker.protocol import validate

ROOT = Path(__file__).resolve().parents[3] / "github" / "protocol" / "v1"
KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
JOB_ID = "fixture-job-0001"


class TestExamples:
    @pytest.mark.parametrize("name", ["manifest", "result"])
    def test_examples_match_their_schema(self, name):
        validate(name, json.loads((ROOT / "examples" / f"{name}.example.json").read_text()))

    def test_schemas_in_the_repository_match_the_packaged_ones(self):
        from vethuq_worker.protocol import schema

        for name in ("manifest", "result"):
            assert json.loads((ROOT / f"{name}.schema.json").read_text()) == schema(name)


class TestFixtures:
    def test_sealed_result_opens_with_the_published_key(self):
        sealed = (ROOT / "fixtures" / "out" / "result.bin").read_bytes()
        result = open_result(KEY, JOB_ID, sealed)
        assert result.status == "done"
        assert [p.text for p in result.pages] == ["Hello world", "Second page"]

    def test_sealed_payload_is_decryptable(self):
        from vethuq_worker import container, crypto

        blob = (ROOT / "fixtures" / "payload" / "payload.bin").read_bytes()
        entries = container.unpack(
            crypto.open_sealed(KEY, "payload", JOB_ID, blob), max_bytes=10**7
        )
        assert sorted(entries) == ["images/0001.png", "images/0002.png", "manifest.json"]
