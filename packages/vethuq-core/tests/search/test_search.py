import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines import (
    FallbackSearchEngine,
    SearchEngines,
    SearchEngineUnavailable,
)
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


def _add_source(conn: sqlite3.Connection, path: str = "/docs") -> int:
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES (?, 'folder', 'indexed', ?)",
        (path, now),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_document(
    conn: sqlite3.Connection,
    source_id: int,
    file_path: str,
    file_type: str = "pdf",
    status: str = "indexed",
    document_id: int | None = None,
) -> int:
    """Insert a `document_index` row, creating a fresh logical `documents` row unless `document_id`
    (another row's logical document, to link this one as sharing its content) is given."""
    if document_id is None:
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        ).lastrowid
    cursor = conn.execute(
        "INSERT INTO document_index "
        "(source_id, document_id, file_path, file_type, status) VALUES (?, ?, ?, ?, ?)",
        (source_id, document_id, file_path, file_type, status),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_pdf_page(conn: sqlite3.Connection, document_id: int, page_number: int, text: str) -> None:
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (?, ?, ?, 0.95)",
        (document_id, page_number, text),
    )
    conn.commit()


def _add_image_page(conn: sqlite3.Connection, document_id: int, text: str) -> None:
    conn.execute(
        "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (?, ?, 0.95)",
        (document_id, text),
    )
    conn.commit()


class TestSearch:
    def test_files_collapses_pages_into_one_result_per_file(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        report = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, report, 1, "budget overview")
        _add_pdf_page(conn, report, 2, "final budget numbers")
        memo = _add_document(conn, source_id, "/docs/memo.pdf")
        _add_pdf_page(conn, memo, 1, "budget memo")

        files = Search.files(storage, "budget")

        assert [(f.file_name, f.is_duplicate) for f in files] == [
            ("memo.pdf", False),
            ("report.pdf", False),
        ]

    def test_files_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.files(storage, "") == []

    def test_search_matches_pdf_page(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")

        matches = Search.indexed_content(storage, "amount due")

        assert len(matches) == 1
        match = matches[0]
        assert match.file_id == document_id
        assert match.file_name == "invoice.pdf"
        assert match.page_number == 1
        assert match.total_pages == 1
        assert match.matched == "amount due"
        assert "Total " in match.before
        assert ": $1,200.00 by Friday." in match.after

    def test_search_matches_image_page(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/scan.png", file_type="image")
        _add_image_page(conn, document_id, "Signed by John Doe on 2026-01-01")

        matches = Search.indexed_content(storage, "john doe")

        assert len(matches) == 1
        assert matches[0].file_name == "scan.png"
        assert matches[0].page_number is None
        assert matches[0].total_pages is None
        assert matches[0].matched == "John Doe"

    def test_search_excludes_removed_source(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")
        conn.execute(
            "UPDATE sources SET is_active = 0, status = 'removed' WHERE id = ?", (source_id,)
        )
        conn.commit()

        matches = Search.indexed_content(storage, "amount due")

        assert matches == []

    def test_search_is_case_insensitive(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/letter.pdf")
        _add_pdf_page(conn, document_id, 1, "URGENT NOTICE")

        matches = Search.indexed_content(storage, "urgent")

        assert len(matches) == 1

    def test_search_returns_one_row_per_matching_page(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, document_id, 1, "budget overview")
        _add_pdf_page(conn, document_id, 2, "no match here")
        _add_pdf_page(conn, document_id, 3, "final budget numbers")

        matches = Search.indexed_content(storage, "budget")

        assert len(matches) == 2
        assert [m.file_id for m in matches] == [document_id, document_id]
        assert [m.page_number for m in matches] == [1, 3]
        assert [m.total_pages for m in matches] == [3, 3]

    def test_search_returns_every_occurrence_within_a_page(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, document_id, 1, "Budget up, budget down.\nBUDGET flat")
        _add_pdf_page(conn, document_id, 2, "one budget")

        matches = Search.indexed_content(storage, "budget", context_chars=4)

        assert [(m.page_number, m.matched) for m in matches] == [
            (1, "Budget"),
            (1, "budget"),
            (1, "BUDGET"),
            (2, "budget"),
        ]
        assert matches[0].before == "" and matches[0].after == " up,"
        assert matches[1].before == "up, " and matches[1].after == " dow"
        assert matches[2].before == "wn. " and matches[2].after == " fla"

    def test_search_occurrences_do_not_overlap(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/a.pdf")
        _add_pdf_page(conn, document_id, 1, "aaaa")

        assert len(Search.indexed_content(storage, "aa")) == 2

    def test_search_ignores_non_indexed_documents(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/pending.pdf", status="pending")
        _add_pdf_page(conn, document_id, 1, "confidential findings")

        matches = Search.indexed_content(storage, "confidential")

        assert matches == []

    def test_search_no_matches_returns_empty_list(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/notes.pdf")
        _add_pdf_page(conn, document_id, 1, "nothing relevant")

        assert Search.indexed_content(storage, "unrelated term") == []

    def test_search_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.indexed_content(storage, "") == []

    def test_search_snippet_context_is_configurable(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        _add_pdf_page(conn, document_id, 1, text)

        SearchSettings.set_snippet_context_chars(storage, 10)
        matches = Search.indexed_content(storage, "target")

        assert len(matches) == 1
        assert matches[0].before == "x" * 10
        assert matches[0].after == "y" * 10
        assert matches[0].truncated_before is True
        assert matches[0].truncated_after is True

    def test_search_returns_duplicate_as_its_own_flagged_result(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        original_id = _add_document(conn, source_id, "/docs/original.pdf")
        _add_pdf_page(conn, original_id, 1, "Total amount due: $1,200.00 by Friday.")
        original_document_id = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
        ).fetchone()["document_id"]
        duplicate_id = _add_document(
            conn, source_id, "/docs/copy.pdf", document_id=original_document_id
        )

        matches = Search.indexed_content(storage, "amount due")

        assert len(matches) == 2
        by_file_id = {m.file_id: m for m in matches}
        assert by_file_id[original_id].duplicate_of_path is None
        assert by_file_id[duplicate_id].file_name == "copy.pdf"
        assert by_file_id[duplicate_id].duplicate_of_path == "/docs/original.pdf"
        assert by_file_id[duplicate_id].matched == "amount due"
        assert by_file_id[duplicate_id].total_pages == 1

    def test_search_matches_substring_inside_a_word(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        # The FTS5 index backing this search is trigram-tokenized specifically so
        # a query landing mid-word (not just on a whole-word/token boundary)
        # still matches, same as the plain substring scan this replaced.
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "a very large invoice")

        matches = Search.indexed_content(storage, "arge")

        assert len(matches) == 1
        assert matches[0].matched == "arge"

    def test_search_escapes_like_wildcard_characters(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, document_id, 1, "50% off, item_code: A1")

        # A literal "%"/"_" in the query must not act as a SQL LIKE wildcard.
        assert len(Search.indexed_content(storage, "50%")) == 1
        assert Search.indexed_content(storage, "50X") == []
        assert len(Search.indexed_content(storage, "item_code")) == 1
        assert Search.indexed_content(storage, "itemXcode") == []

    def test_search_context_chars_argument_overrides_setting(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        _add_pdf_page(conn, document_id, 1, text)

        matches = Search.indexed_content(storage, "target", context_chars=5)

        assert matches[0].before == "x" * 5
        assert matches[0].after == "y" * 5


class TestSearchEngines:
    def test_registry_default_and_unknown(self, storage: Storage):
        assert SearchEngines.get(storage).name == "like"
        with pytest.raises(ValueError, match="Unknown search engine"):
            SearchEngines.get(storage, "nope")

    def test_fallback_engine_uses_fallback_when_primary_unavailable(self, storage: Storage):
        class Broken:
            name = "broken"

            def search(self, query, *, context_chars=None, case_sensitive=False):
                raise SearchEngineUnavailable

        engine = FallbackSearchEngine(Broken(), SearchEngines.get(storage))
        assert engine.name == "broken->like"
        assert engine.search("") == []


def _seed_page(conn: sqlite3.Connection, text: str, path: str = "/docs/museum.pdf") -> int:
    source_id = _add_source(conn, path=path + ".source")
    document_id = _add_document(conn, source_id, path)
    _add_pdf_page(conn, document_id, 1, text)
    return document_id


class TestEngineRegistry:
    def test_lists_all_engines_and_matches_settings(self):
        assert SearchEngines.available() == sorted(SearchSettings.ENGINES)


class TestLikeCaseSensitivity:
    def test_case_sensitive_only_matches_same_case(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        _seed_page(conn, "The Museum opens; the museum closes.")

        insensitive = Search.indexed_content(storage, "museum")
        sensitive = Search.indexed_content(storage, "museum", case_sensitive=True)

        assert [m.matched for m in insensitive] == ["Museum", "museum"]
        assert [m.matched for m in sensitive] == ["museum"]


class TestExactEngine:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("museum", []),
            ("Museum", ["Museum"]),
            ("Museums", []),
            ("Mus", []),
            ("seu", []),
        ],
    )
    def test_is_case_sensitive_and_whole_word(
        self, conn: sqlite3.Connection, storage: Storage, query: str, expected: list[str]
    ):
        _seed_page(conn, "Visit the Museum today")

        matches = Search.indexed_content(storage, query, engine="exact")

        assert [m.matched for m in matches] == expected

    def test_does_not_match_inside_a_longer_word(self, conn: sqlite3.Connection, storage: Storage):
        _seed_page(conn, "Museums and the Museum-shop, Museum.")

        matches = Search.indexed_content(storage, "Museum", engine="exact")

        assert [(m.before, m.after) for m in matches] == [
            ("Museums and the ", "-shop, Museum."),
            ("Museums and the Museum-shop, ", "."),
        ]

    def test_matches_symbols_and_phrases_literally(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        _seed_page(conn, "Total due: $1,200.00 by Friday (50% off)")

        assert len(Search.indexed_content(storage, "$1,200.00", engine="exact")) == 1
        assert len(Search.indexed_content(storage, "due: $1,200.00", engine="exact")) == 1
        assert len(Search.indexed_content(storage, "50%", engine="exact")) == 1
        assert Search.indexed_content(storage, "$1,20", engine="exact") == []
        assert Search.indexed_content(storage, "", engine="exact") == []

    def test_ignores_case_sensitive_flag(self, conn: sqlite3.Connection, storage: Storage):
        _seed_page(conn, "Visit the Museum today")

        assert Search.indexed_content(storage, "museum", engine="exact", case_sensitive=False) == []
        assert (
            len(Search.indexed_content(storage, "Museum", engine="exact", case_sensitive=True)) == 1
        )


class TestFullTextEngine:
    @pytest.mark.parametrize(
        ("query", "hit"),
        [
            ("museum", True),
            ("MUSEUM", True),
            ("Museums", True),  # stemmed
            ("mus", False),  # not a whole word...
            ("mus*", True),  # ...unless it's a prefix query
            ("seu", False),
            ("euma", False),
        ],
    )
    def test_matches_whole_words_stemmed(
        self, conn: sqlite3.Connection, storage: Storage, query: str, hit: bool
    ):
        _seed_page(conn, "Visit the Museum today")

        matches = Search.indexed_content(storage, query, engine="full-text")

        assert bool(matches) is hit
        assert all(m.matched.lower().startswith("museum") for m in matches)

    def test_highlights_the_matched_word_with_context(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        _seed_page(conn, "Two Museums stand near one museum.\nOpen daily.")

        matches = Search.indexed_content(storage, "museum", engine="full-text", context_chars=6)

        assert [(m.before, m.matched, m.after) for m in matches] == [
            ("Two ", "Museums", " stand"),
            ("r one ", "museum", ". Open"),
        ]
        assert not any("\x02" in m.before + m.matched + m.after for m in matches)

    def test_phrase_and_all_terms_required(self, conn: sqlite3.Connection, storage: Storage):
        _seed_page(conn, "amount due by Friday, total amount is high", path="/docs/a.pdf")
        _seed_page(conn, "the due amount is small", path="/docs/b.pdf")

        phrase = Search.indexed_content(storage, '"amount due"', engine="full-text")
        both = Search.indexed_content(storage, "due amount", engine="full-text")

        assert [m.file_name for m in phrase] == ["a.pdf"]
        assert {m.file_name for m in both} == {"a.pdf", "b.pdf"}
        assert Search.indexed_content(storage, "amount zebra", engine="full-text") == []

    def test_folds_accents(self, conn: sqlite3.Connection, storage: Storage):
        _seed_page(conn, "Un caf\u00e9 au lait")

        assert len(Search.indexed_content(storage, "cafe", engine="full-text")) == 1

    def test_ranks_best_page_first(self, conn: sqlite3.Connection, storage: Storage):
        _seed_page(conn, "budget " * 10 + "filler " * 40, path="/docs/z_many.pdf")
        _seed_page(conn, "one budget among " + "filler " * 40, path="/docs/a_few.pdf")

        matches = Search.indexed_content(storage, "budget", engine="full-text")

        assert matches[0].file_name == "z_many.pdf"
        assert matches[0].score is not None and matches[-1].score is not None
        assert matches[0].score > matches[-1].score

    def test_treats_operators_and_punctuation_as_text(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        _seed_page(conn, "salt AND pepper, not sugar: NEAR the sea - fresh")

        for query in ('"unbalanced', "AND", "NEAR(", "sugar:", "-fresh", "salt OR", "*", "()"):
            Search.indexed_content(storage, query, engine="full-text")  # must not raise

        assert len(Search.indexed_content(storage, "AND", engine="full-text")) == 1
        assert Search.indexed_content(storage, "*", engine="full-text") == []
        assert Search.indexed_content(storage, "   ", engine="full-text") == []

    def test_rejects_case_sensitive(self, storage: Storage):
        with pytest.raises(ValueError, match="case-insensitive"):
            Search.indexed_content(storage, "museum", engine="full-text", case_sensitive=True)

    def test_finds_image_pages_and_excludes_non_indexed(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        image_id = _add_document(conn, source_id, "/docs/scan.png", file_type="image")
        _add_image_page(conn, image_id, "Signed by John Doe")
        pending_id = _add_document(conn, source_id, "/docs/p.pdf", status="pending")
        _add_pdf_page(conn, pending_id, 1, "John Doe pending")

        matches = Search.indexed_content(storage, "john", engine="full-text")

        assert [m.file_name for m in matches] == ["scan.png"]
        assert matches[0].page_number is None

    def test_index_follows_page_updates_and_deletes(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        document_id = _seed_page(conn, "alpha beta")
        conn.execute(
            "UPDATE pdf_pages SET ocr_text = 'gamma delta' WHERE document_id = ?", (document_id,)
        )
        conn.commit()

        assert Search.indexed_content(storage, "alpha", engine="full-text") == []
        assert len(Search.indexed_content(storage, "gamma", engine="full-text")) == 1

        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
        conn.commit()
        assert Search.indexed_content(storage, "gamma", engine="full-text") == []

    def test_returns_duplicate_as_its_own_result(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        original_id = _add_document(conn, source_id, "/docs/original.pdf")
        _add_pdf_page(conn, original_id, 1, "Total amount due")
        logical = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
        ).fetchone()["document_id"]
        _add_document(conn, source_id, "/docs/copy.pdf", document_id=logical)

        matches = Search.indexed_content(storage, "amount", engine="full-text")

        assert {m.file_name: m.duplicate_of_path for m in matches} == {
            "original.pdf": None,
            "copy.pdf": "/docs/original.pdf",
        }
        assert all(m.total_pages == 1 for m in matches)


class TestResolveOptions:
    def test_falls_back_to_settings(self, storage: Storage):
        assert Search.resolve_options(storage, None, None) == ("like", False)

        SearchSettings.set_case_sensitive(storage, True)
        assert Search.resolve_options(storage, None, None) == ("like", True)
        assert Search.resolve_options(storage, "like", False) == ("like", False)

        # A stored preference the engine can't honour is dropped, not an error...
        assert Search.resolve_options(storage, "exact", None) == ("exact", True)
        assert Search.resolve_options(storage, "full-text", None) == ("full-text", False)
        SearchSettings.set_engine(storage, "full-text")
        assert Search.resolve_options(storage, None, None) == ("full-text", False)

    def test_rejects_what_the_engine_cannot_honour(self, storage: Storage):
        with pytest.raises(SearchOptionError) as unknown:
            Search.resolve_options(storage, "nope", None)
        assert unknown.value.option == "engine"

        with pytest.raises(SearchOptionError) as full_text:
            Search.resolve_options(storage, "full-text", True)
        assert full_text.value.option == "case_sensitive"

        with pytest.raises(SearchOptionError) as exact:
            Search.resolve_options(storage, "exact", False)
        assert exact.value.option == "case_sensitive"
