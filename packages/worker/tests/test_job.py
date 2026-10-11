from __future__ import annotations

import json
import re

import pytest
from worker_helpers import EN, TE, UNAVAILABLE, request

from vethuq_addon_api.testing import FakeExecutor
from vethuq_worker import (
    JobBuilder,
    JobError,
    StaticEngine,
    crypto,
    generate_key,
    open_result,
    run_job,
    to_ocr_results,
    using,
)
from vethuq_worker.protocol import MAX_PAGES, Manifest, validate
from vethuq_worker.worker import PAYLOAD_FILE, RESULT_FILE

KEY = generate_key()


def engine(executor=None, languages=(EN, TE, UNAVAILABLE)):
    return using(StaticEngine(executor or FakeExecutor(default="read"), list(languages)))


def send(tmp_path, builder, key=KEY):
    folder = tmp_path / "in"
    folder.mkdir(exist_ok=True)
    (folder / PAYLOAD_FILE).write_bytes(builder.build())
    return folder


class TestRoundTrip:
    def test_pages_are_read_and_returned(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("d1.l1.1:0"))
        builder.add(request("d1.l1.2:0", TE, phase="quick", size_factor=2.5))
        executor = FakeExecutor({"d1.l1.1:0": "first page", "d1.l1.2:0": "రెండవ"})
        result = run_job(
            builder.job_id, send(tmp_path, builder), tmp_path / "out", KEY, engine(executor)
        )
        assert result.status == "done"
        assert [r.key for r in executor.seen] == ["d1.l1.1:0", "d1.l1.2:0"]
        assert executor.seen[1].language.id == "te"
        assert executor.seen[1].size_factor == 2.5
        assert executor.seen[0].image.shape == (30, 40, 3)

        sealed = (tmp_path / "out" / RESULT_FILE).read_bytes()
        read = open_result(KEY, builder.job_id, sealed)
        assert read.status == "done"
        found = to_ocr_results(read)
        assert found["d1.l1.1:0"].text == "first page"
        assert found["d1.l1.2:0"].text == "రెండవ"
        assert found["d1.l1.1:0"].lines[0][0] == "first page"
        assert read.billable_seconds >= 0

    def test_pixels_survive_the_round_trip(self, tmp_path):
        seen = []

        class Spy(FakeExecutor):
            def recognize(self, req):
                seen.append(req.image.copy())
                return super().recognize(req)

        builder = JobBuilder(KEY)
        builder.add(request("a", shade=7))
        run_job(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY, engine(Spy()))
        assert (seen[0] == 7).all()

    def test_the_payload_holds_no_readable_content(self, tmp_path):
        builder = JobBuilder(KEY, addon_settings={"pdf": {"licence": "secret-token"}})
        builder.add(request("a-secret-key"))
        blob = builder.build()
        assert b"secret-token" not in blob and b"a-secret-key" not in blob
        assert b"PNG" not in blob


class TestPartialAndFailures:
    def test_unavailable_language_fails_only_that_page(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("ok"))
        builder.add(request("gone", UNAVAILABLE))
        builder.add(request("missing-lang", type(EN)("zz", "Nope")))
        result = run_job(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY, engine())
        assert result.status == "partial"
        errors = {p.key: p.error_code for p in result.pages if not p.ok}
        assert errors == {"gone": "language_unavailable", "missing-lang": "language_unavailable"}

    def test_engine_error_is_reported_without_its_message(self, tmp_path):
        class Boom(FakeExecutor):
            def recognize(self, req):
                raise RuntimeError("private text from the page")

        builder = JobBuilder(KEY)
        builder.add(request("a"))
        result = run_job(
            builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY, engine(Boom())
        )
        assert result.status == "failed"
        assert result.pages[0].error_code == "ocr_failed"
        assert "private text" not in json.dumps(result.to_dict())

    def test_logs_carry_no_page_content(self, tmp_path, caplog):
        class Boom(FakeExecutor):
            def recognize(self, req):
                raise RuntimeError("private text from the page")

        builder = JobBuilder(KEY)
        builder.add(request("secret-key"))
        with caplog.at_level("DEBUG"):
            run_job(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY, engine(Boom()))
        assert "private text" not in caplog.text and "secret-key" not in caplog.text


class TestEnforcement:
    def test_wrong_key_cannot_be_answered(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        folder = send(tmp_path, builder)
        other = generate_key()
        result = run_job(builder.job_id, folder, tmp_path / "o", other, engine())
        assert result.status == "failed" and result.error_code == "bad_payload"
        with pytest.raises(JobError):  # sealed for the other key, so the owner can't open it
            open_result(KEY, builder.job_id, (tmp_path / "o" / RESULT_FILE).read_bytes())

    def test_failures_are_sealed_for_the_client(self, tmp_path):
        folder = tmp_path / "in"
        folder.mkdir()
        (folder / PAYLOAD_FILE).write_bytes(b"garbage")
        run_job("job-00000001", folder, tmp_path / "o", KEY, engine())
        read = open_result(KEY, "job-00000001", (tmp_path / "o" / RESULT_FILE).read_bytes())
        assert read.status == "failed" and read.error_code == "bad_payload"

    def test_missing_payload_is_a_failed_result(self, tmp_path):
        (tmp_path / "in").mkdir()
        result = run_job("job-00000001", tmp_path / "in", tmp_path / "o", KEY, engine())
        assert result.status == "failed"

    def test_payload_for_another_job_id_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        result = run_job("other-job-id", send(tmp_path, builder), tmp_path / "o", KEY, engine())
        assert result.error_code == "bad_payload"

    def test_worker_caps_win_over_the_manifest(self, tmp_path):
        builder = JobBuilder(KEY, max_pages=MAX_PAGES)
        builder.add(request("a"))
        builder.add(request("b"))
        manifest = builder.manifest().to_dict()
        manifest["limits"]["max_pages"] = 1  # the job itself asks for less
        from vethuq_worker import container

        entries = {"manifest.json": json.dumps(manifest).encode()}
        entries.update(builder._images)
        blob = crypto.seal(KEY, "payload", builder.job_id, container.pack(entries))
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(blob)
        result = run_job(builder.job_id, tmp_path / "in", tmp_path / "o", KEY, engine())
        assert result.error_code == "too_many_pages"

    def test_manifest_for_another_job_is_refused(self, tmp_path):
        builder = JobBuilder(KEY, job_id="job-aaaaaaaa")
        builder.add(request("a"))
        folder = send(tmp_path, builder)
        # the payload was sealed for job-aaaaaaaa; asking for another id can't open it at all
        result = run_job("job-bbbbbbbb", folder, tmp_path / "o", KEY, engine())
        assert result.status == "failed"

    def test_unknown_protocol_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        manifest = builder.manifest().to_dict()
        manifest["protocol"] = 2
        from vethuq_worker import container

        blob = crypto.seal(
            KEY,
            "payload",
            builder.job_id,
            container.pack({"manifest.json": json.dumps(manifest).encode(), **builder._images}),
        )
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(blob)
        result = run_job(builder.job_id, tmp_path / "in", tmp_path / "o", KEY, engine())
        assert result.error_code == "unsupported_protocol"

    def test_unknown_manifest_fields_are_ignored(self):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        document = builder.manifest().to_dict()
        document["future_field"] = {"x": 1}
        assert Manifest.from_dict(document).job_id == builder.job_id


class TestBuilder:
    def test_caps_are_checked_as_pages_are_added(self):
        builder = JobBuilder(KEY, max_pages=2)
        builder.add(request("a"))
        builder.add(request("b"))
        assert not builder.fits()
        with pytest.raises(JobError) as caught:
            builder.add(request("c"))
        assert caught.value.code == "too_many_pages"

    def test_size_cap(self):
        builder = JobBuilder(KEY, max_bytes=10)
        with pytest.raises(JobError) as caught:
            builder.add(request("a"))
        assert caught.value.code == "too_large"

    def test_caps_never_exceed_the_protocol_limits(self):
        builder = JobBuilder(KEY, max_pages=10_000)
        assert builder.manifest().max_pages == MAX_PAGES

    def test_duplicate_keys_and_empty_jobs_are_refused(self):
        builder = JobBuilder(KEY)
        with pytest.raises(JobError):
            builder.build()
        builder.add(request("a"))
        with pytest.raises(JobError):
            builder.add(request("a"))

    def test_job_ids_are_unique_and_valid(self):
        ids = {JobBuilder(KEY).job_id for _ in range(20)}
        assert len(ids) == 20
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{8,64}", i) for i in ids)

    def test_a_bad_key_is_refused_up_front(self):
        with pytest.raises(JobError):
            JobBuilder("nope")

    def test_image_paths_are_accepted(self, tmp_path):
        from PIL import Image

        path = tmp_path / "p.jpg"
        Image.new("RGB", (20, 10), "white").save(path)
        builder = JobBuilder(KEY)
        builder.add(type(request("a"))("a", str(path), EN))
        assert len(builder) == 1 and builder.size > 0


class TestResult:
    def test_result_for_another_job_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        run_job(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY, engine())
        sealed = (tmp_path / "o" / RESULT_FILE).read_bytes()
        with pytest.raises(JobError):
            open_result(KEY, "someone-elses-job", sealed)

    def test_result_that_breaks_the_schema_is_refused(self):
        sealed = crypto.seal(KEY, "result", "job-00000001", json.dumps({"protocol": 1}).encode())
        with pytest.raises(JobError) as caught:
            open_result(KEY, "job-00000001", sealed)
        assert caught.value.code == "bad_result"

    def test_result_with_an_unknown_protocol_is_refused(self):
        document = {"protocol": 9, "job_id": "job-00000001", "status": "done", "pages": []}
        sealed = crypto.seal(KEY, "result", "job-00000001", json.dumps(document).encode())
        with pytest.raises(JobError) as caught:
            open_result(KEY, "job-00000001", sealed)
        assert caught.value.code == "unsupported_protocol"

    def test_validate_names_the_failing_place(self):
        with pytest.raises(JobError) as caught:
            validate("manifest", {"protocol": 1, "job_id": "short", "limits": {}, "pages": []})
        assert caught.value.code == "bad_manifest"
