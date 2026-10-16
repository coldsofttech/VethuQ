"""The OCR models are downloaded once and cached, and held to the image's lock."""

from __future__ import annotations

import json

import pytest
from worker_helpers import request

from vethuq_worker import JobBuilder, JobCrypto, ResultReader, Worker
from vethuq_worker.cli import WorkerCli
from vethuq_worker.errors import JobError
from vethuq_worker.models import ModelLock, ModelLockError, ModelsCheck


@pytest.fixture
def models(tmp_path):
    folder = tmp_path / "models"
    (folder / "det").mkdir(parents=True)
    (folder / "det" / "det.onnx").write_bytes(b"detector" * 100)
    (folder / "rec.onnx").write_bytes(b"recogniser" * 100)
    return folder


class TestLock:
    def test_it_records_every_file_with_its_size_and_hash(self, models):
        lock = ModelLock.build(models)

        assert set(lock.files) == {"det/det.onnx", "rec.onnx"}
        digest, size = lock.files["rec.onnx"]
        assert size == 1000 and len(digest) == 64

    def test_it_round_trips_through_a_file(self, models, tmp_path):
        lock = ModelLock.build(models)
        lock.write(tmp_path / "lock" / "models.lock.json")

        assert ModelLock.read(tmp_path / "lock" / "models.lock.json").files == lock.files
        assert json.loads(lock.to_json())["version"] == 1

    def test_matching_models_verify(self, models):
        ModelLock.build(models).verify(models)

    def test_a_missing_file_a_changed_file_and_a_wrong_size_are_all_refused(self, models):
        lock = ModelLock.build(models)
        (models / "rec.onnx").write_bytes(b"x" * 1000)  # same size, other bytes
        (models / "det" / "det.onnx").write_bytes(b"short")
        problems = lock.problems(models)
        assert "rec.onnx: does not match the lock" in problems
        assert "det/det.onnx: wrong size" in problems
        (models / "rec.onnx").unlink()
        assert "rec.onnx: missing" in lock.problems(models)
        with pytest.raises(ModelLockError, match="not what this image expects"):
            lock.verify(models)

    def test_a_link_in_place_of_a_file_is_refused(self, models, tmp_path):
        lock = ModelLock.build(models)
        outside = tmp_path / "elsewhere.onnx"
        outside.write_bytes((models / "rec.onnx").read_bytes())
        (models / "rec.onnx").unlink()
        (models / "rec.onnx").symlink_to(outside)

        assert lock.problems(models) == ["rec.onnx: missing"]

    def test_files_the_lock_does_not_list_are_ignored(self, models):
        lock = ModelLock.build(models)
        (models / "other-image.onnx").write_bytes(b"another variant's model")

        assert lock.problems(models) == []

    def test_an_empty_folder_cannot_be_locked(self, tmp_path):
        with pytest.raises(ModelLockError, match="no models"):
            ModelLock.build(tmp_path)

    @pytest.mark.parametrize("name", ["../escape", "/abs", "a/../../b", "a\\b", ""])
    def test_a_lock_naming_an_unsafe_path_is_refused(self, name):
        text = json.dumps({"version": 1, "files": {name: {"sha256": "0" * 64, "size": 1}}})

        with pytest.raises(ModelLockError, match="unsafe path"):
            ModelLock.from_json(text)

    @pytest.mark.parametrize(
        "text", ["not json", "{}", '{"version": 2, "files": {}}', '{"version": 1, "files": 3}']
    )
    def test_a_damaged_lock_is_refused(self, text):
        with pytest.raises(ModelLockError):
            ModelLock.from_json(text)

    def test_a_lock_that_cannot_be_read_says_so(self, tmp_path):
        with pytest.raises(ModelLockError, match="can't be read"):
            ModelLock.read(tmp_path / "nope.json")


class TestBeforeAJob:
    @pytest.fixture
    def lock(self, models, tmp_path):
        path = tmp_path / "models.lock.json"
        ModelLock.build(models).write(path)
        return path

    def test_good_models_pass(self, models, lock):
        ModelsCheck.before_a_job(models, lock)

    def test_with_no_lock_nothing_is_checked(self, models, tmp_path):
        ModelsCheck.before_a_job(models, None)
        ModelsCheck.before_a_job(None, tmp_path / "absent.json")

    def test_empty_or_absent_models_say_to_fetch_them(self, tmp_path, lock):
        for where in (None, tmp_path / "nowhere", tmp_path / "empty"):
            (tmp_path / "empty").mkdir(exist_ok=True)
            with pytest.raises(JobError) as refused:
                ModelsCheck.before_a_job(where, lock)
            assert refused.value.code == "models_missing" and "fetch-models" in str(refused.value)

    def test_changed_models_are_refused(self, models, lock):
        (models / "rec.onnx").write_bytes(b"tampered")

        with pytest.raises(JobError) as refused:
            ModelsCheck.before_a_job(models, lock)

        assert refused.value.code == "models_unverified"


class TestTheWorkerHoldsJobsToTheLock:
    def test_a_job_with_unverified_models_gets_a_sealed_failure_that_says_why(
        self, models, tmp_path, monkeypatch
    ):
        lock = tmp_path / "models.lock.json"
        ModelLock.build(models).write(lock)
        (models / "rec.onnx").write_bytes(b"tampered")
        monkeypatch.setenv("VETHUQ_MODELS", str(models))
        monkeypatch.setenv(ModelsCheck.LOCK_VARIABLE, str(lock))
        key = JobCrypto.generate_key()
        builder = JobBuilder(key)
        builder.add(request("a"))
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / Worker.PAYLOAD_FILE).write_bytes(builder.build())

        result = Worker().run(builder.job_id, tmp_path / "in", tmp_path / "out", key)

        assert result.status == "failed" and result.error_code == "models_unverified"
        sealed = (tmp_path / "out" / Worker.RESULT_FILE).read_bytes()
        assert ResultReader(key).read(builder.job_id, sealed).error_code == "models_unverified"


class TestCommands:
    @pytest.fixture
    def baker(self, monkeypatch, models):
        """A Baker that 'downloads' a model file into the folder it is given."""
        calls = []

        class FakeBaker:
            def __init__(self, folder, say=print):
                self.folder = folder

            def run(self):
                calls.append(self.folder)
                self.folder.mkdir(parents=True, exist_ok=True)
                (self.folder / "m.onnx").write_bytes(b"model" * 10)
                return 3

        monkeypatch.setattr("vethuq_worker.bake.Baker", FakeBaker)
        return calls

    def test_bake_writes_the_lock_beside_the_models(self, baker, tmp_path, capsys):
        folder, lock = tmp_path / "baked", tmp_path / "out" / "models.lock.json"

        code = WorkerCli.main(["bake-models", "--models", str(folder), "--lock", str(lock)])

        assert code == 0 and set(ModelLock.read(lock).files) == {"m.onnx"}
        assert "3 engine(s) ready" in capsys.readouterr().out

    def test_fetch_fills_the_folder_and_checks_it_against_the_lock(self, baker, tmp_path):
        built = tmp_path / "built"
        built.mkdir()
        (built / "m.onnx").write_bytes(b"model" * 10)
        lock = tmp_path / "models.lock.json"
        ModelLock.build(built).write(lock)
        cache = tmp_path / "cache"

        code = WorkerCli.main(["fetch-models", "--models", str(cache), "--lock", str(lock)])

        assert code == 0 and baker == [cache]

    def test_fetch_refuses_models_that_do_not_match_the_lock(self, baker, tmp_path, capsys):
        built = tmp_path / "built"
        built.mkdir()
        (built / "m.onnx").write_bytes(b"what the image build saw")
        lock = tmp_path / "models.lock.json"
        ModelLock.build(built).write(lock)

        code = WorkerCli.main(
            ["fetch-models", "--models", str(tmp_path / "cache"), "--lock", str(lock)]
        )

        assert code == 1 and "not what this image expects" in capsys.readouterr().err

    def test_fetch_without_a_lock_still_fetches(self, baker, tmp_path):
        assert WorkerCli.main(["fetch-models", "--models", str(tmp_path / "c")]) == 0

    def test_fetch_takes_its_places_from_the_environment(self, baker, tmp_path, monkeypatch):
        monkeypatch.setenv("VETHUQ_MODELS", str(tmp_path / "from-env"))
        monkeypatch.delenv(ModelsCheck.LOCK_VARIABLE, raising=False)

        assert WorkerCli.main(["fetch-models"]) == 0 and baker == [tmp_path / "from-env"]

    def test_fetch_with_nowhere_to_put_them_is_a_usage_error(self, baker, monkeypatch, capsys):
        monkeypatch.delenv("VETHUQ_MODELS", raising=False)

        assert WorkerCli.main(["fetch-models"]) == 2
        assert "--models" in capsys.readouterr().err

    def test_a_failed_download_is_a_failure(self, tmp_path, monkeypatch, capsys):
        from vethuq_worker.bake import BakeError

        class Failing:
            def __init__(self, folder, say=print):
                pass

            def run(self):
                raise BakeError("Models failed to download: det.")

        monkeypatch.setattr("vethuq_worker.bake.Baker", Failing)

        assert WorkerCli.main(["fetch-models", "--models", str(tmp_path)]) == 1
        assert "failed to download" in capsys.readouterr().err
