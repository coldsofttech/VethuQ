from __future__ import annotations

import json
import re

import pytest
from worker_helpers import EN, TE, UNAVAILABLE, request

from vethuq_addon_api import OcrRequest
from vethuq_addon_api.testing import FakeExecutor
from vethuq_worker import (
    JobBuilder,
    JobCrypto,
    JobError,
    Manifest,
    Protocol,
    ResultReader,
    StaticEngine,
    Worker,
)
from vethuq_worker.container import Container

PAYLOAD_FILE = Worker.PAYLOAD_FILE
RESULT_FILE = Worker.RESULT_FILE
KEY = JobCrypto.generate_key()


def worker(executor=None, languages=(EN, TE, UNAVAILABLE)):
    return Worker.with_engine(
        StaticEngine(executor or FakeExecutor(default="read"), list(languages))
    )


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
        result = worker(executor).run(
            builder.job_id, send(tmp_path, builder), tmp_path / "out", KEY
        )
        assert result.status == "done"
        assert [r.key for r in executor.seen] == ["d1.l1.1:0", "d1.l1.2:0"]
        assert executor.seen[1].language.id == "te"
        assert executor.seen[1].size_factor == 2.5
        assert executor.seen[0].image.shape == (30, 40, 3)

        sealed = (tmp_path / "out" / RESULT_FILE).read_bytes()
        read = ResultReader(KEY).read(builder.job_id, sealed)
        assert read.status == "done"
        found = read.to_ocr_results()
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
        worker(Spy()).run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        assert (seen[0] == 7).all()

    def test_the_payload_holds_no_readable_content(self, tmp_path):
        builder = JobBuilder(KEY, addon_settings={"pdf": {"licence": "secret-token"}})
        builder.add(request("a-secret-key"))
        blob = builder.build()
        assert b"secret-token" not in blob and b"a-secret-key" not in blob
        assert b"PNG" not in blob


class TestAngles:
    def test_one_image_is_read_at_several_angles_and_sent_once(self, tmp_path):
        picture = request("base").image
        builder = JobBuilder(KEY)
        for angle in (0, 90, 180):
            builder.add(
                OcrRequest(
                    f"p:{angle}", picture, EN, phase="moderate", size_factor=1.0, angle=angle
                )
            )
        manifest = builder.manifest()
        assert [(p.file, p.angle, p.phase) for p in manifest.pages] == [
            ("images/0001.png", 0, "moderate"),
            ("images/0001.png", 90, "moderate"),
            ("images/0001.png", 180, "moderate"),
        ]
        one = JobBuilder(KEY)
        one.add(request("single"))
        assert builder.size == one.size  # the image's bytes are counted once

    def test_the_worker_reads_each_angle_and_decodes_the_image_once(self, tmp_path, monkeypatch):
        from vethuq_worker.images import Images

        decoded = []
        original = Images.from_png
        monkeypatch.setattr(
            Images, "from_png", staticmethod(lambda data: decoded.append(1) or original(data))
        )
        picture = request("base").image
        builder = JobBuilder(KEY)
        for angle in (90, 270):
            builder.add(OcrRequest(f"p:{angle}", picture, EN, phase="moderate", angle=angle))
        executor = FakeExecutor(default="read")
        result = worker(executor).run(
            builder.job_id, send(tmp_path, builder), tmp_path / "out", KEY
        )
        assert result.status == "done"
        assert [(r.phase, r.angle) for r in executor.seen] == [("moderate", 90), ("moderate", 270)]
        assert len(decoded) == 1

    def test_a_different_image_is_a_different_file(self):
        builder = JobBuilder(KEY)
        builder.add(request("a", shade=10))
        builder.add(request("b", shade=200))
        assert [p.file for p in builder.manifest().pages] == ["images/0001.png", "images/0002.png"]

    def test_the_angle_is_part_of_the_manifest_and_defaults_to_upright(self):
        builder = JobBuilder(KEY)
        builder.add(request("a", angle=450))
        document = builder.manifest().to_dict()
        assert document["pages"][0]["angle"] == 90
        del document["pages"][0]["angle"]
        assert Manifest.from_dict(document).pages[0].angle == 0


class TestPartialAndFailures:
    def test_unavailable_language_fails_only_that_page(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("ok"))
        builder.add(request("gone", UNAVAILABLE))
        builder.add(request("missing-lang", type(EN)("zz", "Nope")))
        result = worker().run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        assert result.status == "partial"
        errors = {p.key: p.error_code for p in result.pages if not p.ok}
        assert errors == {"gone": "language_unavailable", "missing-lang": "language_unavailable"}

    def test_engine_error_is_reported_without_its_message(self, tmp_path):
        class Boom(FakeExecutor):
            def recognize(self, req):
                raise RuntimeError("private text from the page")

        builder = JobBuilder(KEY)
        builder.add(request("a"))
        result = worker(Boom()).run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
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
            worker(Boom()).run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        assert "private text" not in caplog.text and "secret-key" not in caplog.text


class TestEnforcement:
    def test_wrong_key_cannot_be_answered(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        folder = send(tmp_path, builder)
        other = JobCrypto.generate_key()
        result = worker().run(builder.job_id, folder, tmp_path / "o", other)
        assert result.status == "failed" and result.error_code == "bad_payload"
        with pytest.raises(JobError):  # sealed for the other key, so the owner can't open it
            ResultReader(KEY).read(builder.job_id, (tmp_path / "o" / RESULT_FILE).read_bytes())

    def test_failures_are_sealed_for_the_client(self, tmp_path):
        folder = tmp_path / "in"
        folder.mkdir()
        (folder / PAYLOAD_FILE).write_bytes(b"garbage")
        worker().run("job-00000001", folder, tmp_path / "o", KEY)
        read = ResultReader(KEY).read("job-00000001", (tmp_path / "o" / RESULT_FILE).read_bytes())
        assert read.status == "failed" and read.error_code == "bad_payload"

    def test_missing_payload_is_a_failed_result(self, tmp_path):
        (tmp_path / "in").mkdir()
        result = worker().run("job-00000001", tmp_path / "in", tmp_path / "o", KEY)
        assert result.status == "failed"

    def test_payload_for_another_job_id_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        result = worker().run("other-job-id", send(tmp_path, builder), tmp_path / "o", KEY)
        assert result.error_code == "bad_payload"

    def test_worker_caps_win_over_the_manifest(self, tmp_path):
        builder = JobBuilder(KEY, max_pages=Protocol.MAX_PAGES)
        builder.add(request("a"))
        builder.add(request("b"))
        manifest = builder.manifest().to_dict()
        manifest["limits"]["max_pages"] = 1  # the job itself asks for less
        entries = {"manifest.json": json.dumps(manifest).encode()}
        entries.update(builder._images)
        blob = JobCrypto(KEY).seal("payload", builder.job_id, Container.pack(entries))
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(blob)
        result = worker().run(builder.job_id, tmp_path / "in", tmp_path / "o", KEY)
        assert result.error_code == "too_many_pages"

    def test_manifest_for_another_job_is_refused(self, tmp_path):
        builder = JobBuilder(KEY, job_id="job-aaaaaaaa")
        builder.add(request("a"))
        folder = send(tmp_path, builder)
        # the payload was sealed for job-aaaaaaaa; asking for another id can't open it at all
        result = worker().run("job-bbbbbbbb", folder, tmp_path / "o", KEY)
        assert result.status == "failed"

    def test_unknown_protocol_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        manifest = builder.manifest().to_dict()
        manifest["protocol"] = 2
        blob = JobCrypto(KEY).seal(
            "payload",
            builder.job_id,
            Container.pack({"manifest.json": json.dumps(manifest).encode(), **builder._images}),
        )
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(blob)
        result = worker().run(builder.job_id, tmp_path / "in", tmp_path / "o", KEY)
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
        assert builder.manifest().max_pages == Protocol.MAX_PAGES

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
        worker().run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        sealed = (tmp_path / "o" / RESULT_FILE).read_bytes()
        with pytest.raises(JobError):
            ResultReader(KEY).read("someone-elses-job", sealed)

    def test_result_that_breaks_the_schema_is_refused(self):
        sealed = JobCrypto(KEY).seal("result", "job-00000001", json.dumps({"protocol": 1}).encode())
        with pytest.raises(JobError) as caught:
            ResultReader(KEY).read("job-00000001", sealed)
        assert caught.value.code == "bad_result"

    def test_result_with_an_unknown_protocol_is_refused(self):
        document = {"protocol": 9, "job_id": "job-00000001", "status": "done", "pages": []}
        sealed = JobCrypto(KEY).seal("result", "job-00000001", json.dumps(document).encode())
        with pytest.raises(JobError) as caught:
            ResultReader(KEY).read("job-00000001", sealed)
        assert caught.value.code == "unsupported_protocol"

    def test_validate_names_the_failing_place(self):
        with pytest.raises(JobError) as caught:
            Protocol.validate(
                "manifest", {"protocol": 1, "job_id": "short", "limits": {}, "pages": []}
            )
        assert caught.value.code == "bad_manifest"


class TestOwner:
    """A licence that lists GitHub owner ids is for those owners only (the workflow gives the
    worker the owner's id)."""

    @staticmethod
    def verifier(mismatch_for):
        from types import SimpleNamespace

        def verify(token, github_owner_id=None, **_):
            bad = token == mismatch_for and github_owner_id != 7
            return SimpleNamespace(status=SimpleNamespace(name="OWNER_MISMATCH" if bad else "OK"))

        return verify

    def run(self, tmp_path, owner, monkeypatch, tokens=("bound",)):
        from vethuq_worker.owner import VARIABLE

        if owner is None:
            monkeypatch.delenv(VARIABLE, raising=False)
        else:
            monkeypatch.setenv(VARIABLE, str(owner))
        builder = JobBuilder(
            KEY, addon_settings={f"a{i}": {"licence": t} for i, t in enumerate(tokens)}
        )
        builder.add(request("k"))
        folder = send(tmp_path, builder)
        engine = StaticEngine(FakeExecutor(default="read"), [EN])
        return Worker.with_engine(engine, self.verifier("bound")).run(
            builder.job_id, folder, tmp_path / "out", KEY
        )

    def test_a_listed_owner_is_accepted(self, tmp_path, monkeypatch):
        assert self.run(tmp_path, 7, monkeypatch).status == "done"

    def test_another_owner_is_refused_with_a_clear_code(self, tmp_path, monkeypatch):
        result = self.run(tmp_path, 8, monkeypatch)
        assert (result.status, result.error_code) == ("failed", "owner_mismatch")

    def test_a_licence_with_no_owner_list_is_not_affected(self, tmp_path, monkeypatch):
        assert self.run(tmp_path, 8, monkeypatch, tokens=("free",)).status == "done"

    def test_outside_github_nothing_is_checked(self, tmp_path, monkeypatch):
        assert self.run(tmp_path, None, monkeypatch).status == "done"

    def test_a_bad_owner_id_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VETHUQ_GITHUB_OWNER_ID", "abc")
        builder = JobBuilder(KEY)
        builder.add(request("k"))
        result = worker().run(builder.job_id, send(tmp_path, builder), tmp_path / "out", KEY)
        assert result.error_code == "owner_mismatch"


class TestProfiles:
    def test_the_manifest_names_the_profile_of_each_phase(self):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        builder.add(request("b", phase="moderate"))
        assert builder.manifest().profiles == {"quick": "fast", "moderate": "advanced"}

    def test_the_result_reports_the_cpu_and_the_profiles_used(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        builder.add(request("b", phase="moderate"))
        result = worker().run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        assert result.runner["profiles"] == ["advanced", "fast"] and result.runner["cpu_model"]

    def test_an_unknown_profile_is_refused(self, tmp_path):
        builder = JobBuilder(KEY)
        builder.add(request("a"))
        builder.manifest = lambda real=builder.manifest: _with(real(), {"quick": "turbo"})
        result = worker().run(builder.job_id, send(tmp_path, builder), tmp_path / "o", KEY)
        assert result.error_code == "bad_manifest"  # the schema refuses it first


def _with(manifest, profiles):
    from dataclasses import replace

    return replace(manifest, profiles=profiles)
