from __future__ import annotations

import json

import pytest

import vethuq
from vethuq._db import _Language


class TestLanguage:
    def test_details(self):
        language = vethuq.Language(id=1, language="en")

        assert (language.id, language.language) == (1, "en")

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            vethuq.Language(1, "en").language = "te"

    def test_to_dict_and_json(self):
        language = vethuq.Language(1, "en")

        assert language.to_dict() == {"id": 1, "language": "en"}
        assert json.loads(language.to_json()) == language.to_dict()
        assert "\n" in language.to_json(indent=2)


class TestLanguages:
    @pytest.fixture
    def client(self, tmp_path):
        with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
            yield client

    def test_list_all_has_english_out_of_the_box(self, client):
        assert client.languages.list_all() == [vethuq.Language(id=1, language="en")]

    def test_list_all_returns_language_objects(self, client):
        assert all(isinstance(item, vethuq.Language) for item in client.languages.list_all())

    def test_list_all_includes_languages_added_later(self, client):
        client.languages.list_all()
        with client._db().session() as session:
            session.add(_Language(language="te"))

        assert [item.language for item in client.languages.list_all()] == ["en", "te"]

    def test_every_listed_language_can_be_used_for_a_source(self, client, tmp_path):
        ids = [item.language for item in client.languages.list_all()]

        assert client.sources.create(tmp_path, languages=ids).languages == ids

    def test_languages_object_is_reused(self, client):
        assert client.languages is client.languages

    def test_nothing_is_created_until_first_use(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")
        client.languages

        assert not (tmp_path / "db").exists()

    def test_close_then_use_again(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.languages.list_all()
        client.close()

        assert [item.language for item in client.languages.list_all()] == ["en"]
        client.close()
