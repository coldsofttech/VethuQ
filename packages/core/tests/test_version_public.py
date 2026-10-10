from __future__ import annotations

import json
import platform

import pytest

import vethuq
from vethuq._db import _Schema


class TestVersionDetails:
    def test_fields_and_defaults(self):
        details = vethuq.VersionDetails(vethuq="1.0.0", python="3.13", platform="x", db_schema=1)

        assert details.file_types == details.search_engines == details.ocr_engines == ()
        assert details.ocr_languages == details.add_ons == details.bundles == ()

    def test_is_frozen(self):
        details = vethuq.VersionDetails("1", "3", "x", 1)
        with pytest.raises(AttributeError):
            details.vethuq = "2"

    def test_to_dict_uses_lists_and_has_every_field(self):
        details = vethuq.VersionDetails("1.0.0", "3.13", "x", 2, file_types=("pdf",))

        assert details.to_dict() == {
            "vethuq": "1.0.0",
            "python": "3.13",
            "platform": "x",
            "db_schema": 2,
            "file_types": ["pdf"],
            "search_engines": [],
            "ocr_engines": [],
            "ocr_languages": [],
            "add_ons": [],
            "bundles": [],
        }

    def test_to_json_matches_to_dict(self):
        details = vethuq.VersionDetails("1.0.0", "3.13", "x", 2)

        assert json.loads(details.to_json()) == details.to_dict()
        assert "\n" in details.to_json(indent=2)

    def test_is_exported_from_the_package(self):
        assert vethuq.VersionDetails is vethuq.version.VersionDetails


class TestClientVersion:
    @pytest.fixture
    def client(self, tmp_path):
        with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
            yield client

    def test_returns_version_details(self, client):
        assert isinstance(client.version, vethuq.VersionDetails)

    def test_vethuq_is_the_app_version(self, client):
        assert client.version.vethuq == vethuq.APP_VERSION

    def test_python_and_platform(self, client):
        assert client.version.python == platform.python_version()
        assert client.version.platform == platform.platform()

    def test_db_schema_is_the_current_version(self, client):
        assert client.version.db_schema == _Schema.VERSION == 1

    def test_the_placeholders_are_empty(self, client):
        version = client.version

        assert version.file_types == () and version.search_engines == ()
        assert version.ocr_engines == () and version.ocr_languages == ()
        assert version.add_ons == () and version.bundles == ()

    def test_reading_it_does_not_open_or_create_the_database(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")

        client.version

        assert not (tmp_path / "db").exists()

    def test_it_works_on_a_closed_client(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.close()

        assert client.version.vethuq == vethuq.APP_VERSION

    def test_the_json_output(self, client):
        data = json.loads(client.version.to_json())

        assert data["vethuq"] == vethuq.APP_VERSION
        assert data["db_schema"] == 1
        assert data["add_ons"] == [] and data["bundles"] == []

    def test_a_database_from_a_newer_vethuq_is_refused_but_version_still_reads(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "vethuq.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            conn.execute("INSERT INTO schema_version VALUES (99)")
        client = vethuq.VethuQ(db_path=db_path)

        assert client.version.db_schema == 1
        with pytest.raises(vethuq.errors.SchemaVersionError):
            client.sources.list()
