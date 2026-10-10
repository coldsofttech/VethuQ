from __future__ import annotations

import json

import pytest

import vethuq
from vethuq import errors


class TestSource:
    def test_an_unsaved_source_only_has_what_was_described(self):
        source = vethuq.Source("~/docs", languages=["en", "te"])

        assert (source.path, source.languages) == ("~/docs", ["en", "te"])
        assert source.id is None and source.status is None and source.added_at is None

    def test_path_is_required(self):
        with pytest.raises(TypeError):
            vethuq.Source()

    def test_a_path_object_is_stored_as_text(self, tmp_path):
        assert vethuq.Source(tmp_path).path == str(tmp_path)

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            vethuq.Source("x").path = "y"

    def test_languages_are_copied(self):
        languages = ["en"]
        source = vethuq.Source("x", languages=languages)
        languages.append("te")

        assert source.languages == ["en"]

    def test_to_dict_leaves_out_languages_when_there_are_none(self):
        data = vethuq.Source("x").to_dict()

        assert "languages" not in data
        assert set(data) == {"id", "path", "type", "status", "added_at", "last_scanned_at"}

    def test_to_json_matches_to_dict(self):
        source = vethuq.Source("x", languages=["en"])

        assert json.loads(source.to_json()) == source.to_dict()
        assert "\n" in source.to_json(indent=2)


class TestVethuQClient:
    @pytest.fixture
    def client(self, tmp_path):
        with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
            yield client

    def test_create_from_a_path_returns_the_details(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()

        source = client.sources.create(folder)

        assert isinstance(source, vethuq.Source)
        assert source.id == 1
        assert source.path == str(folder.resolve())
        assert (source.source_type, source.status, source.is_active) == ("folder", "pending", True)
        assert source.added_at and source.last_scanned_at is None and source.removed_at is None
        assert source.languages is None

    def test_create_with_languages(self, client, tmp_path):
        source = client.sources.create(tmp_path, languages=["en"])

        assert source.languages == ["en"]

    def test_create_from_a_source_object(self, client, tmp_path):
        described = vethuq.Source(tmp_path, languages=["en"])

        created = client.sources.create(described)

        assert created.id == 1 and created.languages == ["en"]
        assert described.id is None  # the one passed in is left untouched

    def test_the_result_has_json(self, client, tmp_path):
        data = json.loads(client.sources.create(tmp_path).to_json())

        assert data["id"] == 1 and data["type"] == "folder" and data["status"] == "pending"

    def test_languages_must_be_a_list(self, client, tmp_path):
        with pytest.raises(TypeError):
            client.sources.create(tmp_path, languages="en,te")

    def test_an_unknown_language_is_rejected_with_the_available_ones(self, client, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError) as excinfo:
            client.sources.create(tmp_path, languages=["en", "xx"])

        assert "'xx'" in excinfo.value.message
        assert "en" in excinfo.value.hint

    def test_a_source_with_an_unknown_language_is_not_created(self, client, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError):
            client.sources.create(vethuq.Source(tmp_path, languages=["xx"]))

        assert client.sources.create(tmp_path).id == 1

    def test_english_is_available_out_of_the_box(self, client, tmp_path):
        assert client.sources.create(tmp_path, languages=["EN"]).languages == ["en"]

    def test_languages_on_both_the_source_and_the_call_is_ambiguous(self, client, tmp_path):
        with pytest.raises(TypeError, match="not both"):
            client.sources.create(vethuq.Source(tmp_path, ["en"]), languages=["te"])

    def test_a_created_source_cannot_be_created_again(self, client, tmp_path):
        created = client.sources.create(tmp_path)

        with pytest.raises(errors.SourceAlreadyExistsError):
            client.sources.create(created)

    def test_errors_are_the_public_ones(self, client, tmp_path):
        with pytest.raises(errors.SourcePathError):
            client.sources.create(tmp_path / "missing")
        client.sources.create(tmp_path)
        with pytest.raises(errors.SourceError):
            client.sources.create(tmp_path)
        with pytest.raises(errors.VethuQError):
            client.sources.create(tmp_path)

    def test_sources_are_shared_by_clients_of_the_same_database(self, client, tmp_path):
        client.sources.create(tmp_path)

        with vethuq.VethuQ(db_path=client.db_path) as other:
            with pytest.raises(errors.SourceAlreadyExistsError):
                other.sources.create(tmp_path)

    def test_default_database_is_the_paths_db_path(self):
        client = vethuq.VethuQ()
        assert client.db_path == vethuq.Paths.db_path()

        source_path = client.db_path.parent.parent  # the isolated data root: a real folder
        source_path.mkdir(parents=True, exist_ok=True)
        assert client.sources.create(source_path).id == 1
        assert client.db_path.is_file()
        client.close()

    def test_nothing_is_created_until_first_use(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")
        client.sources

        assert not (tmp_path / "db").exists()

    def test_close_then_use_again(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.sources.create(tmp_path)
        client.close()

        with pytest.raises(errors.SourceAlreadyExistsError):
            client.sources.create(tmp_path)
        client.close()

    def test_sources_object_is_reused(self, client):
        assert client.sources is client.sources
