"""Telugu text read by OCR is indexed and found by every kind of search."""

from __future__ import annotations

import sys

import pytest

import vethuq
from tests import fake_pipeline as fp
from tests.language_addons import TELUGU, LanguageAddonFactory

TEXT = "ఇది అమ్మ ఇల్లు. కాకి ఎగిరింది. తెలుగు భాష చాలా బాగుంది"


@pytest.fixture
def client(tmp_path_factory, monkeypatch, tmp_path):
    folder = tmp_path_factory.mktemp("telugu")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    module = LanguageAddonFactory.install(
        folder, "telugu", [{**TELUGU, "script_ranges": ((0x0C00, 0x0C7F),)}]
    )
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        root = tmp_path / "docs"
        root.mkdir()
        (root / "scan.pdf").write_text(
            fp.pdf_document(fp.scanned_page(TEXT, confidence=0.95)),
            encoding="utf-8",
        )
        english = tmp_path / "docs_en"
        english.mkdir()
        (english / "english.pdf").write_text(
            fp.pdf_document(fp.native_page("An English page about the museum today.")),
            encoding="utf-8",
        )
        client.sources.create(root, languages=["te"])
        client.sources.create(english, languages=["en"])
        assert client.index.run().status.value == "completed"
        yield client
    LanguageAddonFactory.forget(module)


def files(result):
    return {m.file_name for m in result}


@pytest.mark.parametrize("engine", ["exact", "like", "lexical", "full-text", "fuzzy"])
def test_a_telugu_word_is_found(client, engine):
    assert files(client.search.run("కాకి", engine=engine)) == {"scan.pdf"}


def test_a_phrase_is_found_by_the_proximity_engine(client):
    assert files(client.search.run("తెలుగు బాగుంది", engine="proximity")) == {"scan.pdf"}


def test_a_word_is_not_found_by_its_bare_consonants(client):
    assert files(client.search.run("కక", engine="exact")) == set()


def test_a_short_query_is_found_without_the_index(client):
    assert files(client.search.run("అమ్మ", engine="like")) == {"scan.pdf"}


def test_english_is_unaffected(client):
    assert files(client.search.run("museum", engine="exact")) == {"english.pdf"}
