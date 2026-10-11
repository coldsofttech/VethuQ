from __future__ import annotations

from worker_helpers import EN, request

from vethuq_addon_api.testing import FakeExecutor
from vethuq_worker import (
    JobBuilder,
    StaticEngine,
    generate_key,
    open_result,
    using,
    worker,
)
from vethuq_worker.cli import KEY_VARIABLE, main
from vethuq_worker.worker import PAYLOAD_FILE, RESULT_FILE


class TestCli:
    def test_missing_key_is_a_usage_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv(KEY_VARIABLE, raising=False)
        code = main(["run", "--job-id", "x", "--payload", str(tmp_path), "--out", str(tmp_path)])
        assert code == 2
        assert KEY_VARIABLE in capsys.readouterr().err

    def test_bad_key_is_a_usage_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(KEY_VARIABLE, "nope")
        code = main(["run", "--job-id", "x", "--payload", str(tmp_path), "--out", str(tmp_path)])
        assert code == 2
        assert "bad_key" in capsys.readouterr().err

    def test_failed_job_exits_one_and_writes_a_result(self, tmp_path, monkeypatch, capsys):
        key = generate_key()
        monkeypatch.setenv(KEY_VARIABLE, key)
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(b"junk")
        code = main(
            [
                "run",
                "--job-id",
                "job-00000001",
                "--payload",
                str(tmp_path / "in"),
                "--out",
                str(tmp_path / "o"),
            ]
        )
        assert code == 1
        read = open_result(key, "job-00000001", (tmp_path / "o" / RESULT_FILE).read_bytes())
        assert read.status == "failed"
        assert "failed" in capsys.readouterr().out

    def test_good_job_exits_zero(self, tmp_path, monkeypatch, capsys):
        key = generate_key()
        monkeypatch.setenv(KEY_VARIABLE, key)
        monkeypatch.setattr(
            worker, "core_engine", using(StaticEngine(FakeExecutor(default="hi"), [EN]))
        )
        builder = JobBuilder(key)
        builder.add(request("a"))
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / PAYLOAD_FILE).write_bytes(builder.build())
        args = ["--job-id", builder.job_id, "--payload", str(tmp_path / "in")]
        assert main(["run", *args, "--out", str(tmp_path / "o")]) == 0
        assert "1/1 pages read" in capsys.readouterr().out
        read = open_result(key, builder.job_id, (tmp_path / "o" / RESULT_FILE).read_bytes())
        assert read.pages[0].text == "hi"
