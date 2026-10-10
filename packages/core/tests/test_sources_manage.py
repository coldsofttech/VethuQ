from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import vethuq
from vethuq import errors
from vethuq._db import _Language, _Source, _SourceLanguage


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        with client._db().session():  # make sure the database exists
            pass
        yield client


@pytest.fixture
def folders(tmp_path):
    """Three folders under tmp_path, named so path order differs from creation order."""
    paths = {}
    for name in ("charlie", "alpha", "bravo"):
        (tmp_path / name).mkdir()
        paths[name] = tmp_path / name
    return paths


@pytest.fixture
def three(client, folders, tmp_path):
    """Sources 1=charlie, 2=alpha (a file's parent is a folder), 3=bravo (a file)."""
    file = tmp_path / "bravo.pdf"
    file.write_text("x")
    one = client.sources.create(folders["charlie"])
    two = client.sources.create(folders["alpha"], languages=["en"])
    three = client.sources.create(file)
    return one, two, three


def _add_language(client, code):
    with client._db().session() as session:
        session.add(_Language(language=code))


def _set(client, source_id, **fields):
    with client._db().session() as session:
        row = session.get(_Source, source_id)
        for name, value in fields.items():
            setattr(row, name, value)


class TestSourcesGet:
    def test_by_id(self, client, three):
        assert client.sources.get(2) == three[1]

    def test_by_path_string(self, client, three):
        assert client.sources.get(three[0].path) == three[0]

    def test_by_path_object_and_with_a_tilde_or_dots(self, client, three, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

        assert client.sources.get(tmp_path / "alpha").id == 2
        assert client.sources.get("~/alpha").id == 2
        assert client.sources.get(tmp_path / "bravo" / ".." / "alpha").id == 2

    def test_a_string_of_digits_is_a_path_not_an_id(self, client, three):
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.get("1")

    def test_returns_the_full_details(self, client, three):
        source = client.sources.get(2)

        assert isinstance(source, vethuq.sources.Source)
        assert source.source_type is vethuq.sources.SourceType.FOLDER
        assert source.status is vethuq.sources.SourceStatus.PENDING
        assert source.languages == ["en"]

    def test_unknown_id_or_path_is_not_found(self, client, three, tmp_path):
        for target in (99, tmp_path / "nowhere"):
            with pytest.raises(errors.SourceNotFoundError) as excinfo:
                client.sources.get(target)
            assert excinfo.value.exit_code == 23

    def test_a_removed_source_is_found_only_when_asked(self, client, three):
        client.sources.remove(1)

        with pytest.raises(errors.SourceNotFoundError) as excinfo:
            client.sources.get(1)
        assert "include_removed" in excinfo.value.hint
        removed = client.sources.get(1, include_removed=True)
        assert removed.status is vethuq.sources.SourceStatus.REMOVED and removed.is_active is False

    def test_include_removed_still_finds_active_sources(self, client, three):
        assert client.sources.get(2, include_removed=True).id == 2

    @pytest.mark.parametrize("bad", [None, 1.5, ["a"], True])
    def test_a_wrong_type_is_rejected(self, client, bad):
        with pytest.raises(TypeError, match="id.*or its path"):
            client.sources.get(bad)


class TestSourcesList:
    def test_lists_active_sources_by_id_ascending(self, client, three):
        assert [s.id for s in client.sources.list()] == [1, 2, 3]

    def test_an_empty_database_lists_nothing(self, client):
        assert client.sources.list() == []

    def test_removed_sources_are_left_out_unless_included(self, client, three):
        client.sources.remove(2)

        assert [s.id for s in client.sources.list()] == [1, 3]
        assert [s.id for s in client.sources.list(include_removed=True)] == [1, 2, 3]

    def test_asking_for_removed_status_shows_them_without_the_flag(self, client, three):
        client.sources.remove(2)

        removed = client.sources.list(status=vethuq.sources.SourceStatus.REMOVED)

        assert [s.id for s in removed] == [2]

    @pytest.mark.parametrize(
        ("sort_by", "order", "expected"),
        [
            (vethuq.sources.SourceSortBy.ID, vethuq.sources.SortOrder.ASC, [1, 2, 3]),
            (vethuq.sources.SourceSortBy.ID, vethuq.sources.SortOrder.DESC, [3, 2, 1]),
            (vethuq.sources.SourceSortBy.PATH, vethuq.sources.SortOrder.ASC, [2, 3, 1]),
            (vethuq.sources.SourceSortBy.PATH, vethuq.sources.SortOrder.DESC, [1, 3, 2]),
            (vethuq.sources.SourceSortBy.ADDED_AT, vethuq.sources.SortOrder.DESC, [3, 2, 1]),
            (vethuq.sources.SourceSortBy.SOURCE_TYPE, vethuq.sources.SortOrder.ASC, [3, 1, 2]),
        ],
    )
    def test_sorting(self, client, three, sort_by, order, expected):
        assert [s.id for s in client.sources.list(sort_by=sort_by, order=order)] == expected

    def test_sorting_by_status_and_last_scanned_at(self, client, three):
        _set(client, 2, status=vethuq.sources.SourceStatus.COMPLETED, last_scanned_at="2026-01-02")
        _set(client, 3, last_scanned_at="2026-01-01")

        by_status = client.sources.list(sort_by="status", order="desc")
        by_scan = client.sources.list(sort_by="last_scanned_at", order="desc")

        assert [s.id for s in by_status] == [1, 3, 2]  # pending, pending, completed; ties by id
        assert [s.id for s in by_scan] == [2, 3, 1]

    def test_ties_are_broken_by_id(self, client, three):
        assert [s.id for s in client.sources.list(sort_by="status", order="desc")] == [1, 2, 3]

    def test_strings_are_accepted_for_the_enums(self, client, three):
        listed = client.sources.list(
            sort_by="path", order="desc", status="pending", source_type="folder"
        )

        assert [s.id for s in listed] == [1, 2]

    def test_filter_by_source_type(self, client, three):
        types = vethuq.sources.SourceType

        assert [s.id for s in client.sources.list(source_type=types.FILE)] == [3]
        assert [s.id for s in client.sources.list(source_type=types.FOLDER)] == [1, 2]

    def test_filter_by_status(self, client, three):
        _set(client, 2, status=vethuq.sources.SourceStatus.COMPLETED)

        completed = client.sources.list(status=vethuq.sources.SourceStatus.COMPLETED)

        assert [s.id for s in completed] == [2]
        assert [s.id for s in client.sources.list(status=vethuq.sources.SourceStatus.ERROR)] == []

    def test_filter_by_language(self, client, three):
        _add_language(client, "te")
        client.sources.set_languages(1, ["te"])
        client.sources.set_languages(3, ["en", "te"])

        assert [s.id for s in client.sources.list(language="en")] == [2, 3]
        assert [s.id for s in client.sources.list(language="TE")] == [1, 3]

    def test_filters_combine(self, client, three):
        assert [s.id for s in client.sources.list(source_type="folder", language="en")] == [2]

    def test_filter_by_an_unknown_language_is_rejected(self, client, three):
        with pytest.raises(errors.LanguageUnavailableError):
            client.sources.list(language="xx")

    def test_invalid_enum_values_are_rejected_with_the_options(self, client, three):
        for argument, bad in (
            ("sort_by", "colour"),
            ("order", "sideways"),
            ("status", "lost"),
            ("source_type", "link"),
        ):
            with pytest.raises(ValueError, match=f"{argument} must be one of"):
                client.sources.list(**{argument: bad})

    def test_a_blank_language_is_rejected(self, client, three):
        with pytest.raises(ValueError, match="language id"):
            client.sources.list(language="  ")

    def test_results_are_source_objects(self, client, three):
        assert all(isinstance(s, vethuq.sources.Source) for s in client.sources.list())


class TestSourcesRemove:
    def test_marks_the_source_removed_and_returns_it(self, client, three):
        removed = client.sources.remove(2)

        assert removed.id == 2
        assert removed.status is vethuq.sources.SourceStatus.REMOVED
        assert removed.is_active is False
        assert datetime.fromisoformat(removed.removed_at).utcoffset().total_seconds() == 0

    def test_by_path(self, client, three):
        assert client.sources.remove(three[0].path).id == 1

    def test_keeps_the_source_and_its_languages(self, client, three):
        client.sources.remove(2)

        assert client.sources.get(2, include_removed=True).languages == ["en"]

    def test_only_that_source_changes(self, client, three):
        client.sources.remove(2)

        assert [s.status for s in client.sources.list(include_removed=True)] == [
            "pending",
            "removed",
            "pending",
        ]

    def test_removing_twice_is_not_found(self, client, three):
        client.sources.remove(2)

        with pytest.raises(errors.SourceNotFoundError):
            client.sources.remove(2)

    def test_unknown_source_is_not_found(self, client):
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.remove(7)

    def test_a_removed_source_can_be_created_again(self, client, three):
        client.sources.remove(2)

        again = client.sources.create(three[1].path)

        assert again.id == 2 and again.status is vethuq.sources.SourceStatus.PENDING
        assert again.is_active is True and again.removed_at is None


class TestSourcesSetLanguages:
    def test_sets_and_returns_the_source(self, client, three):
        _add_language(client, "te")

        updated = client.sources.set_languages(1, ["en", "te"])

        assert updated.id == 1 and updated.languages == ["en", "te"]
        assert client.sources.get(1).languages == ["en", "te"]

    def test_replaces_the_previous_languages(self, client, three):
        _add_language(client, "te")

        assert client.sources.set_languages(2, ["te"]).languages == ["te"]

    def test_setting_the_same_languages_again_works(self, client, three):
        assert client.sources.set_languages(2, ["en"]).languages == ["en"]

    @pytest.mark.parametrize("nothing", [None, []])
    def test_nothing_goes_back_to_the_global_setting(self, client, three, nothing):
        assert client.sources.set_languages(2, nothing).languages is None
        assert client.sources.get(2).languages is None

    def test_by_path(self, client, three):
        assert client.sources.set_languages(three[0].path, ["en"]).languages == ["en"]

    def test_an_unknown_language_is_rejected_and_nothing_changes(self, client, three):
        with pytest.raises(errors.LanguageUnavailableError):
            client.sources.set_languages(2, ["xx"])

        assert client.sources.get(2).languages == ["en"]

    def test_a_string_is_rejected(self, client, three):
        with pytest.raises(TypeError):
            client.sources.set_languages(2, "en")

    def test_a_removed_source_cannot_be_changed(self, client, three):
        client.sources.remove(2)

        with pytest.raises(errors.SourceNotFoundError):
            client.sources.set_languages(2, ["en"])

    def test_unknown_source_is_not_found(self, client):
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.set_languages(5, ["en"])

    def test_the_language_is_checked_before_the_source(self, client):
        with pytest.raises(errors.LanguageUnavailableError):
            client.sources.set_languages(5, ["xx"])


class TestSourcesPurge:
    def test_deletes_a_removed_source_for_good(self, client, three):
        client.sources.remove(2)

        result = client.sources.purge(2)

        assert result == vethuq.sources.PurgeResult(
            id=2, path=three[1].path, source_type=vethuq.sources.SourceType.FOLDER
        )
        assert [s.id for s in client.sources.list(include_removed=True)] == [1, 3]
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.get(2, include_removed=True)

    def test_by_path(self, client, three):
        client.sources.remove(three[2].path)

        result = client.sources.purge(three[2].path)

        assert result.id == 3 and result.source_type is vethuq.sources.SourceType.FILE

    def test_an_active_source_cannot_be_purged(self, client, three):
        with pytest.raises(errors.SourceNotRemovedError) as excinfo:
            client.sources.purge(2)

        assert excinfo.value.exit_code == 24
        assert "Remove it" in excinfo.value.hint
        assert client.sources.get(2).id == 2

    def test_unknown_source_is_not_found(self, client, three):
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.purge(42)

    def test_a_purged_source_cannot_be_purged_again(self, client, three):
        client.sources.remove(2)
        client.sources.purge(2)

        with pytest.raises(errors.SourceNotFoundError):
            client.sources.purge(2)

    def test_the_language_choices_go_with_it(self, client, three):
        client.sources.remove(2)
        client.sources.purge(2)

        with client._db().session() as session:
            # source 2 was the only one with a language, so nothing is left
            assert session.scalars(select(_SourceLanguage)).all() == []

    def test_the_path_can_be_registered_again_afterwards(self, client, three):
        client.sources.remove(2)
        client.sources.purge(2)

        again = client.sources.create(three[1].path)

        assert again.status is vethuq.sources.SourceStatus.PENDING and again.languages is None

    def test_the_result_has_json(self, client, three):
        client.sources.remove(2)

        data = json.loads(client.sources.purge(2).to_json())

        assert data == {"id": 2, "path": three[1].path, "type": "folder"}


class TestSourcesPurgeExpired:
    @staticmethod
    def _removed(client, source_id, ago):
        client.sources.remove(source_id)
        _set(client, source_id, removed_at=(datetime.now(UTC) - ago).isoformat())

    def test_purges_sources_removed_longer_ago_than_the_retention(self, client, three):
        self._removed(client, 1, timedelta(days=8))
        self._removed(client, 2, timedelta(days=6))

        purged = client.sources.purge_expired()

        assert [p.id for p in purged] == [1]
        assert [s.id for s in client.sources.list(include_removed=True)] == [2, 3]

    def test_the_default_retention_is_seven_days(self, client, three):
        self._removed(client, 1, timedelta(days=7, minutes=1))
        self._removed(client, 2, timedelta(days=7) - timedelta(minutes=1))

        assert [p.id for p in client.sources.purge_expired()] == [1]

    def test_uses_the_retention_setting(self, client, three):
        client.settings.sources.set_removed_retention_minutes(60)
        self._removed(client, 1, timedelta(minutes=90))
        self._removed(client, 2, timedelta(minutes=30))

        assert [p.id for p in client.sources.purge_expired()] == [1]

    def test_a_retention_can_be_given_for_one_call(self, client, three):
        self._removed(client, 1, timedelta(minutes=10))

        assert client.sources.purge_expired(retention_minutes=60) == []
        assert [p.id for p in client.sources.purge_expired(retention_minutes=5)] == [1]

    def test_zero_purges_every_removed_source(self, client, three):
        client.settings.sources.set_removed_retention_minutes(0)
        client.sources.remove(1)
        client.sources.remove(3)

        assert [p.id for p in client.sources.purge_expired()] == [1, 3]
        assert [s.id for s in client.sources.list(include_removed=True)] == [2]

    def test_active_sources_are_never_purged(self, client, three):
        _set(client, 2, removed_at=(datetime.now(UTC) - timedelta(days=30)).isoformat())

        assert client.sources.purge_expired() == []
        assert client.sources.get(2).id == 2

    def test_nothing_to_purge(self, client, three):
        assert client.sources.purge_expired() == []

    def test_a_negative_retention_is_rejected(self, client, three):
        with pytest.raises(ValueError, match="negative"):
            client.sources.purge_expired(retention_minutes=-1)

    def test_returns_purge_results(self, client, three):
        self._removed(client, 3, timedelta(days=9))

        (result,) = client.sources.purge_expired()

        assert result == vethuq.sources.PurgeResult(
            id=3, path=three[2].path, source_type=vethuq.sources.SourceType.FILE
        )


class TestSourceEnums:
    def test_created_source_uses_the_enums(self, client, folders):
        source = client.sources.create(folders["alpha"])

        assert source.source_type is vethuq.sources.SourceType.FOLDER
        assert source.status is vethuq.sources.SourceStatus.PENDING

    def test_json_keeps_plain_strings(self, client, folders):
        data = json.loads(client.sources.create(folders["alpha"]).to_json())

        assert data["type"] == "folder" and data["status"] == "pending"
