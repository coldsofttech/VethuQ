from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from vethuq import errors
from vethuq._db import _Database, _Language, _Source, _SourceLanguage
from vethuq._sources import _Sources


class TestSourcesCreate:
    @pytest.fixture
    def database(self, tmp_path):
        database = _Database(tmp_path / "db" / "vethuq.db")
        yield database
        database.dispose()

    @staticmethod
    def _create(database, path, languages=None):
        with database.session() as session:
            source = _Sources.create(session, path, languages)
            return (
                source.id,
                source.path,
                source.source_type,
                source.status,
                source.language_codes or None,
            )

    def test_registers_a_file(self, database, tmp_path):
        file = tmp_path / "a.pdf"
        file.write_text("x")

        source_id, path, source_type, status, languages = self._create(database, file)

        assert (source_id, path, source_type, status, languages) == (
            1,
            str(file.resolve()),
            "file",
            "pending",
            None,
        )

    def test_registers_a_folder(self, database, tmp_path):
        assert self._create(database, tmp_path)[2] == "folder"

    def test_stores_active_source_with_a_utc_timestamp(self, database, tmp_path):
        self._create(database, tmp_path)

        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            assert source.is_active is True
            assert source.removed_at is None and source.last_scanned_at is None
            assert datetime.fromisoformat(source.added_at).utcoffset().total_seconds() == 0

    def test_expands_and_normalises_the_path(self, database, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "docs").mkdir()

        path = self._create(database, "~/docs/../docs")[1]

        assert path == str((tmp_path / "docs").resolve())

    def test_missing_path_is_rejected(self, database, tmp_path):
        with pytest.raises(errors.SourcePathError) as excinfo:
            self._create(database, tmp_path / "missing")

        assert str((tmp_path / "missing").resolve()) in excinfo.value.message
        assert excinfo.value.exit_code == 21

    def test_registering_a_path_twice_is_rejected(self, database, tmp_path):
        self._create(database, tmp_path)

        with pytest.raises(errors.SourceAlreadyExistsError) as excinfo:
            self._create(database, tmp_path)

        assert excinfo.value.exit_code == 22
        assert "source 1" in excinfo.value.hint

    def test_the_same_path_spelled_differently_is_still_a_duplicate(self, database, tmp_path):
        (tmp_path / "docs").mkdir()
        self._create(database, tmp_path / "docs")

        with pytest.raises(errors.SourceAlreadyExistsError):
            self._create(database, tmp_path / "docs" / ".." / "docs")

    def test_a_failed_create_stores_nothing(self, database, tmp_path):
        with pytest.raises(errors.SourcePathError):
            self._create(database, tmp_path / "missing")

        with database.session() as session:
            assert session.scalars(select(_Source)).all() == []

    def test_a_removed_source_is_reactivated(self, database, tmp_path):
        self._create(database, tmp_path, ["en"])
        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            source.is_active, source.status = False, "removed"
            source.removed_at, source.last_scanned_at = "2026-01-01T00:00:00+00:00", "x"

        source_id, _, _, status, languages = self._create(database, tmp_path)

        assert (source_id, status, languages) == (1, "pending", ["en"])
        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            assert source.is_active is True
            assert source.removed_at is None and source.last_scanned_at is None

    def test_unique_path_violation_from_a_race_becomes_already_exists(
        self, database, tmp_path, monkeypatch
    ):
        self._create(database, tmp_path)
        monkeypatch.setattr(_Sources, "find_by_path", staticmethod(lambda session, path: None))

        with pytest.raises(errors.SourceAlreadyExistsError):
            self._create(database, tmp_path)

    def test_ids_are_never_reused(self, database, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        assert self._create(database, tmp_path / "a")[0] == 1
        with database.session() as session:
            session.execute(text("DELETE FROM sources"))

        assert self._create(database, tmp_path / "b")[0] == 2


class TestCleanLanguages:
    @pytest.mark.parametrize(
        ("languages", "expected"),
        [
            (None, None),
            ([], None),
            (["", "  "], None),
            (["en"], ["en"]),
            (["en", "te"], ["en", "te"]),
            ([" EN ", "Te", "en"], ["en", "te"]),
            (("te", "en"), ["te", "en"]),
        ],
    )
    def test_clean_languages(self, languages, expected):
        assert _Sources.clean_languages(languages) == expected

    def test_a_plain_string_is_rejected(self):
        with pytest.raises(TypeError, match="list of language ids"):
            _Sources.clean_languages("en,te")


class TestSourceLanguages:
    @pytest.fixture
    def database(self, tmp_path):
        database = _Database(tmp_path / "db" / "vethuq.db")
        yield database
        database.dispose()

    @staticmethod
    def _add_languages(database, *codes):
        with database.session() as session:
            session.add_all(_Language(language=code) for code in codes)

    @staticmethod
    def _create(database, path, languages=None):
        with database.session() as session:
            return _Sources.create(session, path, languages).language_codes

    @staticmethod
    def _links(database):
        with database.session() as session:
            return [
                (link.source_id, link.language.language)
                for link in session.scalars(select(_SourceLanguage))
            ]

    def test_english_is_seeded(self, database):
        with database.session() as session:
            rows = session.execute(select(_Language.id, _Language.language)).all()

        assert [tuple(row) for row in rows] == [(1, "en")]

    def test_seeding_is_not_repeated(self, database):
        for _ in range(2):
            with database.session():
                pass
            database.dispose()

        with database.session() as session:
            assert session.scalars(select(_Language.language)).all() == ["en"]

    def test_a_source_without_languages_has_no_links(self, database, tmp_path):
        assert self._create(database, tmp_path) == []
        assert self._links(database) == []

    def test_languages_are_stored_in_the_link_table(self, database, tmp_path):
        self._add_languages(database, "te")

        assert self._create(database, tmp_path, ["en", "te"]) == ["en", "te"]
        assert self._links(database) == [(1, "en"), (1, "te")]

    def test_languages_come_back_in_language_order(self, database, tmp_path):
        self._add_languages(database, "te")

        assert self._create(database, tmp_path, ["te", "en"]) == ["en", "te"]

    def test_languages_are_case_insensitive_and_deduplicated(self, database, tmp_path):
        assert self._create(database, tmp_path, [" EN ", "en"]) == ["en"]
        assert len(self._links(database)) == 1

    def test_an_unknown_language_is_rejected(self, database, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError) as excinfo:
            self._create(database, tmp_path, ["xx"])

        assert "'xx'" in excinfo.value.message
        assert "Available languages: en" in excinfo.value.hint
        assert excinfo.value.exit_code == 16

    def test_every_unknown_language_is_reported_at_once(self, database, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError) as excinfo:
            self._create(database, tmp_path, ["en", "xx", "yy"])

        assert "'xx', 'yy'" in excinfo.value.message
        assert "languages" in excinfo.value.message

    def test_a_language_not_yet_added_is_rejected_until_it_is(self, database, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError):
            self._create(database, tmp_path, ["te"])
        self._add_languages(database, "te")

        assert self._create(database, tmp_path, ["te"]) == ["te"]

    def test_an_unknown_language_stores_nothing(self, database, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError):
            self._create(database, tmp_path, ["en", "xx"])

        with database.session() as session:
            assert session.scalars(select(_Source)).all() == []
        assert self._links(database) == []

    def test_reactivating_replaces_the_languages(self, database, tmp_path):
        self._add_languages(database, "te")
        self._create(database, tmp_path, ["en"])
        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            source.is_active, source.status = False, "removed"

        assert self._create(database, tmp_path, ["te"]) == ["te"]
        assert self._links(database) == [(1, "te")]

    def test_reactivating_with_the_same_languages_keeps_them(self, database, tmp_path):
        self._create(database, tmp_path, ["en"])
        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            source.is_active, source.status = False, "removed"

        assert self._create(database, tmp_path, ["en"]) == ["en"]
        assert self._links(database) == [(1, "en")]

    def test_reactivating_without_languages_keeps_the_old_ones(self, database, tmp_path):
        self._create(database, tmp_path, ["en"])
        with database.session() as session:
            source = session.scalars(select(_Source)).one()
            source.is_active, source.status = False, "removed"

        assert self._create(database, tmp_path) == ["en"]

    def test_deleting_a_source_deletes_its_language_links(self, database, tmp_path):
        self._create(database, tmp_path, ["en"])

        with database.session() as session:
            session.execute(text("DELETE FROM sources"))

        assert self._links(database) == []

    def test_a_language_in_use_cannot_be_deleted(self, database, tmp_path):
        self._create(database, tmp_path, ["en"])

        with pytest.raises(IntegrityError):
            with database.session() as session:
                session.execute(text("DELETE FROM languages WHERE language = 'en'"))


class TestDatabase:
    def test_creates_the_folder_and_the_table_on_first_use(self, tmp_path):
        database = _Database(tmp_path / "new" / "db" / "vethuq.db")
        assert not (tmp_path / "new").exists()

        with database.session() as session:
            assert session.execute(text("SELECT COUNT(*) FROM sources")).scalar() == 0

        assert (tmp_path / "new" / "db" / "vethuq.db").is_file()
        database.dispose()

    def test_connections_use_foreign_keys_wal_and_a_busy_timeout(self, tmp_path):
        database = _Database(tmp_path / "vethuq.db")

        with database.session() as session:
            assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert session.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        database.dispose()

    def test_unwritable_folder_is_reported(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        database = _Database(blocker / "vethuq.db")

        with pytest.raises(errors.DataFolderNotWritableError):
            with database.session():
                pass

    def test_session_rolls_back_when_the_block_raises(self, tmp_path):
        database = _Database(tmp_path / "vethuq.db")

        with pytest.raises(RuntimeError):
            with database.session() as session:
                session.add(_Source(path="p", source_type="file", added_at="t"))
                session.flush()
                raise RuntimeError

        with database.session() as session:
            assert session.scalars(select(_Source)).all() == []
        database.dispose()

    def test_schema_rejects_an_invalid_source_type(self, tmp_path):
        database = _Database(tmp_path / "vethuq.db")

        with pytest.raises(IntegrityError):
            with database.session() as session:
                session.add(_Source(path="p", source_type="bogus", added_at="t"))

        database.dispose()

    def test_dispose_then_use_again_reconnects(self, tmp_path):
        database = _Database(tmp_path / "vethuq.db")
        with database.session() as session:
            session.add(_Source(path="p", source_type="file", added_at="t"))
        database.dispose()

        with database.session() as session:
            assert len(session.scalars(select(_Source)).all()) == 1
        database.dispose()
