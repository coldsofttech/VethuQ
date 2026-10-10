from __future__ import annotations

import json
import logging
from datetime import date, datetime

import pytest

import vethuq
from vethuq import errors


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "docs").mkdir()
    return tmp_path / "docs"


class TestLogsAccess:
    def test_one_attribute_per_component_each_its_own_class(self, client):
        assert isinstance(client.logs.database, vethuq.logs.DatabaseLog)
        assert isinstance(client.logs.index, vethuq.logs.IndexLog)
        assert isinstance(client.logs.ui, vethuq.logs.UiLog)
        assert isinstance(client.logs.cli, vethuq.logs.CliLog)

    def test_the_classes_share_one_base(self, client):
        for log in (client.logs.database, client.logs.index, client.logs.ui, client.logs.cli):
            assert isinstance(log, vethuq.logs.Log)
        assert all(
            issubclass(cls, vethuq.logs.Log)
            for cls in (
                vethuq.logs.DatabaseLog,
                vethuq.logs.IndexLog,
                vethuq.logs.UiLog,
                vethuq.logs.CliLog,
            )
        )

    def test_each_knows_its_component_and_what_it_logs(self, client):
        pairs = [
            (client.logs.database, vethuq.logs.LogComponent.DATABASE),
            (client.logs.index, vethuq.logs.LogComponent.INDEX),
            (client.logs.ui, vethuq.logs.LogComponent.UI),
            (client.logs.cli, vethuq.logs.LogComponent.CLI),
        ]
        for log, component in pairs:
            assert log.component is component
            assert log.description

    def test_get_by_enum_or_name(self, client):
        assert client.logs.get(vethuq.logs.LogComponent.UI) is client.logs.ui
        assert client.logs.get("cli") is client.logs.cli

    def test_get_rejects_an_unknown_component(self, client):
        with pytest.raises(errors.InvalidLogRequestError) as excinfo:
            client.logs.get("nope")

        assert excinfo.value.exit_code == 42

    def test_the_logs_object_is_reused(self, client):
        assert client.logs is client.logs

    def test_close_then_use_again(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.logs
        client.close()

        assert len(client.logs.list()) == 4
        client.close()

    def test_reading_logs_does_not_open_or_create_anything(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")

        client.logs.list()
        client.logs.cli.file()
        with pytest.raises(errors.LogNotFoundError):
            client.logs.cli.tail()

        assert not (tmp_path / "db").exists() and not (tmp_path / "logs").exists()


class TestList:
    def test_lists_every_component(self, client):
        files = client.logs.list()

        assert [f.component for f in files] == list(vethuq.logs.LogComponent)
        assert all(isinstance(f, vethuq.logs.LogFile) for f in files)

    def test_only_components_that_have_logged_exist(self, client, folder):
        client.sources.create(folder)

        assert {f.component.value: f.exists for f in client.logs.list()} == {
            "database": True,
            "index": False,
            "ui": False,
            "cli": False,
        }

    def test_paths_are_in_the_logs_folder(self, client, tmp_path):
        paths = {f.component.value: f.path for f in client.logs.list()}

        assert paths["cli"] == str(tmp_path / "logs" / "cli.log")
        assert paths["database"] == str(tmp_path / "logs" / "database.log")


class TestFile:
    def test_a_log_that_exists(self, client, folder):
        client.sources.create(folder)

        file = client.logs.database.file()

        assert file.exists is True and file.size_bytes > 0
        assert datetime.fromisoformat(file.modified_at).utcoffset().total_seconds() == 0
        assert date.today() in file.days

    def test_a_log_that_does_not_exist(self, client):
        file = client.logs.cli.file()

        assert not file.exists
        assert (file.size_bytes, file.modified_at, file.days) == (None, None, ())

    def test_a_past_day_is_the_rotated_file(self, client, tmp_path):
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "cli.log.2026-09-30").write_text("abc")

        file = client.logs.cli.file("2026-09-30")

        assert file.path.endswith("cli.log.2026-09-30")
        assert file.exists and file.size_bytes == 3
        assert file.days == (date(2026, 9, 30),)

    def test_a_date_object_works_too(self, client):
        assert client.logs.cli.file(date(2026, 9, 30)).path.endswith("cli.log.2026-09-30")

    def test_a_bad_day_is_rejected(self, client):
        with pytest.raises(errors.InvalidLogRequestError):
            client.logs.cli.file("yesterday")

    def test_to_dict_and_json(self, client, folder):
        client.sources.create(folder)

        data = json.loads(client.logs.database.file().to_json())

        assert data["component"] == "database" and data["exists"] is True
        assert data["days"] == [date.today().isoformat()]
        assert client.logs.database.file().to_dict() == data

    def test_is_frozen(self, client):
        with pytest.raises(AttributeError):
            client.logs.cli.file().path = "x"


class TestWritingAndReading:
    def test_the_database_log_records_what_happens(self, client, folder):
        client.sources.create(folder)
        client.sources.remove(1)

        messages = [e.message for e in client.logs.database.tail(10)]

        assert any("Created database schema" in m for m in messages)
        assert any(m.startswith("Source created: id=1") for m in messages)
        assert any(m.startswith("Source removed: id=1") for m in messages)

    def test_other_components_write_through_their_logger(self, client):
        logger = client.logs.cli.logger()

        logger.info("ran: sources list")
        logger.error("failed: %s", "boom")

        assert isinstance(logger, logging.Logger) and logger.name == "vethuq.cli"
        assert [e.message for e in client.logs.cli.tail()] == ["ran: sources list", "failed: boom"]
        assert client.logs.ui.file().exists is False

    def test_entries_are_structured(self, client):
        client.logs.cli.logger().warning("careful")

        (entry,) = client.logs.cli.tail()

        assert isinstance(entry, vethuq.logs.LogEntry)
        assert entry.level is vethuq.logs.LogLevel.WARNING
        assert (entry.logger, entry.message) == ("vethuq.cli", "careful")
        assert entry.thread == "MainThread"
        assert isinstance(entry.timestamp, datetime)
        assert entry.raw.endswith("vethuq.cli: careful")

    def test_entry_to_dict_and_json(self, client):
        client.logs.cli.logger().info("hi")
        (entry,) = client.logs.cli.tail()

        data = json.loads(entry.to_json())

        assert data["level"] == "info" and data["message"] == "hi"
        assert data["timestamp"] == entry.timestamp.isoformat()
        assert entry.to_dict() == data and "raw" not in data

    def test_an_entry_in_an_unknown_format_serialises(self):
        entry = vethuq.logs.LogEntry(None, None, None, None, "plain", "plain")

        assert entry.to_dict()["timestamp"] is None and entry.to_dict()["level"] is None

    def test_read_filters_and_sorts(self, client):
        logger = client.logs.cli.logger()
        logger.info("first thing")
        logger.warning("second thing")
        logger.error("third thing")

        assert [e.message for e in client.logs.cli.read()] == [
            "first thing",
            "second thing",
            "third thing",
        ]
        assert [e.message for e in client.logs.cli.read(level=vethuq.logs.LogLevel.WARNING)] == [
            "second thing",
            "third thing",
        ]
        assert [e.message for e in client.logs.cli.read(contains="SECOND")] == ["second thing"]
        assert [e.message for e in client.logs.cli.read(order=vethuq.logs.SortOrder.DESC)][0] == (
            "third thing"
        )

    def test_tail_takes_the_last_entries(self, client):
        logger = client.logs.cli.logger()
        for number in range(5):
            logger.info("entry %d", number)

        assert [e.message for e in client.logs.cli.tail(2)] == ["entry 3", "entry 4"]
        assert [e.message for e in client.logs.cli.tail(2, order="desc")] == ["entry 4", "entry 3"]

    def test_a_traceback_stays_with_its_entry(self, client):
        logger = client.logs.cli.logger()
        try:
            raise ValueError("bad value")
        except ValueError:
            logger.exception("it failed")
        logger.info("after")

        failed, after = client.logs.cli.read()

        assert "ValueError: bad value" in failed.message and "Traceback" in failed.message
        assert after.message == "after"

    def test_a_missing_log_is_reported(self, client):
        for call in (client.logs.cli.tail, client.logs.cli.read):
            with pytest.raises(errors.LogNotFoundError):
                call()

    def test_bad_arguments_are_reported(self, client):
        client.logs.cli.logger().info("x")
        for kwargs in ({"lines": 0}, {"level": "loud"}, {"day": "x"}, {"order": "up"}):
            with pytest.raises(errors.InvalidLogRequestError):
                client.logs.cli.tail(**kwargs)

    def test_errors_are_log_and_vethuq_errors(self, client):
        with pytest.raises(errors.LogError):
            client.logs.cli.tail()
        with pytest.raises(errors.VethuQError):
            client.logs.cli.tail(0)

    def test_follow_yields_new_entries(self, client, monkeypatch):
        from vethuq._logs import _Log

        monkeypatch.setattr(_Log, "FOLLOW_POLL_SECONDS", 0)
        logger = client.logs.cli.logger()
        logger.info("before")
        calls = []

        def stop():
            calls.append(1)
            if len(calls) == 1:
                logger.info("during one")
                logger.error("during two")
            return len(calls) > 2

        seen = list(client.logs.cli.follow(stop=stop))

        assert [e.message for e in seen] == ["during one", "during two"]
        assert all(isinstance(e, vethuq.logs.LogEntry) for e in seen)

    def test_follow_filters(self, client, monkeypatch):
        from vethuq._logs import _Log

        monkeypatch.setattr(_Log, "FOLLOW_POLL_SECONDS", 0)
        logger = client.logs.cli.logger()
        calls = []

        def stop():
            calls.append(1)
            if len(calls) == 1:
                logger.info("quiet")
                logger.error("loud")
            return len(calls) > 2

        assert [e.message for e in client.logs.cli.follow(level="error", stop=stop)] == ["loud"]

    def test_export(self, client, tmp_path):
        logger = client.logs.cli.logger()
        logger.info("one")
        logger.error("two")
        out = tmp_path / "cli.txt"

        assert client.logs.cli.export(out) == 2
        assert client.logs.cli.export(out, level="error") == 1
        assert out.read_text(encoding="utf-8").rstrip().endswith("vethuq.cli: two")
        assert client.logs.cli.export(out, lines=1, order="desc") == 1

    def test_export_of_a_missing_log_is_reported(self, client, tmp_path):
        with pytest.raises(errors.LogNotFoundError):
            client.logs.ui.export(tmp_path / "x.txt")


class TestLogSettingsTakeEffect:
    def test_the_level_decides_what_is_recorded(self, client, folder):
        client.settings.logs.set_level(vethuq.logs.LogLevel.WARNING)
        client.sources.create(folder)
        logger = client.logs.database.logger()
        logger.warning("kept")

        messages = [e.message for e in client.logs.database.read()]

        assert "kept" in messages
        assert not any(m.startswith("Source created") for m in messages)

    def test_changing_the_level_applies_to_a_running_log(self, client):
        logger = client.logs.cli.logger()
        logger.info("recorded")
        client.settings.logs.set_level("error")
        logger.info("dropped")
        logger.error("kept")

        assert [e.message for e in client.logs.cli.read()] == ["recorded", "kept"]

    def test_resetting_the_level_applies_too(self, client):
        client.settings.logs.set_level("error")
        logger = client.logs.cli.logger()
        client.settings.logs.reset_level()
        logger.info("back to info")

        assert [e.message for e in client.logs.cli.read()] == ["back to info"]

    def test_the_retention_is_applied_to_the_handler(self, client):
        logger = client.logs.cli.logger()

        client.settings.logs.set_retention_days(3)

        assert logger.handlers[0].backupCount == 3
        client.settings.logs.reset_retention_days()
        assert logger.handlers[0].backupCount == 15
