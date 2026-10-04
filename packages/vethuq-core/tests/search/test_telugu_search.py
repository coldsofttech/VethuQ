"""Searching Telugu text: every engine, the normalizers and the word index behind them."""

import sqlite3

import pytest
from search_data import SearchData
from vethuq_core.db.queries.documents import Document
from vethuq_core.languages import Scripts
from vethuq_core.search import Search
from vethuq_core.search.engines import SearchEngineUnavailable
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.fulltext import FullTextSearchEngine
from vethuq_core.search.engines.proximity import ProximitySearchEngine
from vethuq_core.search.normalizers import Normalizers
from vethuq_core.search.normalizers.leetspeak import Leet
from vethuq_core.search.normalizers.unicode import UnicodeNormalizer
from vethuq_core.storage import Storage
from vethuq_core.storage.sqlite import SqliteStorage

AMMA = "అమ్మ ఇంటికి వెళ్ళింది"  # mother went home
KAKI = "కాకి చెట్టు మీద కూర్చుంది"  # the crow sat on the tree
KA = "క క క"  # bare consonants
YEAR = "౨౦౨౪ సంవత్సరం"  # 2024 (Telugu digits) year
ENGLISH = "Museum of art"


@pytest.fixture
def pages(conn: sqlite3.Connection):
    """One page per file, with their derived text recorded as the real writer does."""
    for name, text in (
        ("amma", AMMA),
        ("kaki", KAKI),
        ("ka", KA),
        ("year", YEAR),
        ("english", ENGLISH),
    ):
        SearchData.seed_page(conn, text, path=f"/docs/{name}.pdf")
    Document.refresh_derived_text(conn, "pdf_pages")
    conn.commit()


def _found(storage: Storage, query: str, engine: str, **options) -> list[tuple[str, str]]:
    matches = Search.indexed_content(storage, query, engine=engine, **options)
    return [(m.file_name.removesuffix(".pdf"), m.matched) for m in matches]


class TestWordCharacters:
    def test_telugu_signs_belong_to_the_word(self):
        assert Scripts.word_pattern().findall("కాకి అమ్మ, ఇల్లు") == ["కాకి", "అమ్మ", "ఇల్లు"]

    def test_an_accent_still_ends_a_word_as_it_always_did(self):
        assert Scripts.is_word_char("é")
        assert not Scripts.is_word_char("́")
        assert not Scripts.is_word_char("_")
        assert Scripts.is_word_char("ా") and Scripts.is_word_char("్")

    def test_a_joiner_stays_inside_a_telugu_word_only(self):
        assert Scripts.word_pattern().findall("క్‌ష") == ["క్‌ష"]
        assert Scripts.word_pattern().findall("a‌b") == ["a", "b"]

    def test_english_words_are_found_as_before(self):
        assert Scripts.word_pattern().findall("it's état_1 3.14") == [
            "it",
            "s",
            "état_1",
            "3",
            "14",
        ]

    def test_which_text_needs_the_mark_aware_index(self):
        assert Scripts.has_mark_script("invoice కాకి")
        assert not Scripts.has_mark_script("invoice total")


class TestUnicodeNormalizer:
    @pytest.mark.parametrize("word", ["కాకి", "అమ్మ", "క్ష", "ఇల్లు", "ఇంట్లో", "తెలుగు"])
    def test_full_keeps_the_signs_that_make_the_word(self, word):
        assert UnicodeNormalizer().fold(word, "full").text == word

    def test_full_does_not_make_different_words_the_same(self):
        fold = UnicodeNormalizer()

        assert fold.fold("కాకి", "full").text != fold.fold("కక", "full").text

    def test_full_still_folds_accents_next_to_telugu(self):
        assert UnicodeNormalizer().fold("కాకి café", "full").text == "కాకి cafe"

    def test_full_reads_telugu_digits_as_digits(self):
        assert UnicodeNormalizer().fold("౨౦౨౪", "full").text == "2024"

    def test_full_drops_the_joiners_that_only_choose_a_form(self):
        assert UnicodeNormalizer().fold("క్‍ష", "full").text == "క్ష"
        assert UnicodeNormalizer().fold("క్‌ష", "full").text == "క్ష"

    def test_a_joiner_in_other_text_is_left_alone(self):
        assert UnicodeNormalizer().fold("a‍b", "full").text == "a‍b"

    def test_basic_composes_but_changes_nothing_else(self):
        fold = UnicodeNormalizer()

        assert fold.fold("౨౦౨౪ క్‍ష", "basic").text == "౨౦౨౪ క్‍ష"
        # An OCR engine can emit the two parts of a vowel sign; NFC joins them.
        assert fold.fold("ై", "basic").text == "ై"

    def test_positions_trace_back_through_dropped_and_changed_characters(self):
        folded = UnicodeNormalizer().fold("క్‍ష ౨౦౨౪", "full")

        assert folded.text == "క్ష 2024"
        assert folded.original(0, 3) == (0, 4)
        assert folded.original(4, 8) == (5, 9)

    def test_index_form_keeps_the_signs_and_treats_both_kinds_of_digit_alike(self):
        assert Normalizers.index_form("కాకి ౨౦౨౪") == "కాకి zoza"
        assert Normalizers.index_form("కాకి ౨౦౨౪") == Normalizers.index_form("కాకి 2024")


class TestSkeleton:
    def test_the_skeleton_keeps_telugu_signs_instead_of_dropping_them_as_noise(self):
        assert Leet.skeleton("కాకి") == "కాకి"
        assert Leet.skeleton("అమ్మ ఇంటికి") == "అమ్మఇంటికి"

    def test_telugu_marks_are_not_noise(self):
        assert not Leet.is_noise("ా") and not Leet.is_noise("్")
        assert Leet.is_noise(" ") and Leet.is_noise("́")

    def test_a_skeleton_with_text_around_it(self):
        assert Leet.skeleton("p@ss కాకి 123") == "passకాకిize"


class TestEveryEngine:
    @pytest.mark.parametrize("engine", ["like", "exact", "full-text", "fuzzy", "noise-fuzzy"])
    def test_a_word_is_found_whole(self, storage, pages, engine):
        assert _found(storage, "కాకి", engine) == [("kaki", "కాకి")]
        assert _found(storage, "అమ్మ", engine) == [("amma", "అమ్మ")]

    def test_all_engines_together(self, storage, pages):
        results = Search.indexed_pages(storage, "అమ్మ")

        assert [r.file_name for r in results] == ["amma.pdf"]

    def test_like_finds_part_of_a_word_but_the_whole_word_engines_do_not(self, storage, pages):
        assert _found(storage, "కా", "like") == [("kaki", "కా")]
        assert _found(storage, "కా", "exact") == []
        assert _found(storage, "కా", "full-text") == []

    def test_a_single_letter_is_not_found_inside_other_words(self, storage, pages):
        # `క` is a whole word only on the page of bare consonants; in `కాకి` it is a syllable.
        assert {name for name, _ in _found(storage, "క", "exact")} == {"ka"}
        assert {name for name, _ in _found(storage, "క", "full-text")} == {"ka"}
        assert {name for name, _ in _found(storage, "క", "like")} == {"ka", "kaki", "amma"}

    def test_full_text_takes_a_prefix(self, storage, pages):
        assert _found(storage, "ఇంట*", "full-text") == [("amma", "ఇంటికి")]

    def test_full_text_takes_a_phrase(self, storage, pages):
        assert _found(storage, '"అమ్మ ఇంటికి"', "full-text") == [("amma", "అమ్మ ఇంటికి")]
        assert _found(storage, '"ఇంటికి అమ్మ"', "full-text") == []

    def test_full_text_needs_every_word(self, storage, pages):
        assert {n for n, _ in _found(storage, "అమ్మ వెళ్ళింది", "full-text")} == {"amma"}
        assert _found(storage, "అమ్మ కాకి", "full-text") == []

    def test_proximity_counts_telugu_words_between_the_terms(self, storage, conn, pages):
        # One word (ఇంటికి) lies between the terms on the first page, two on the second.
        SearchData.seed_page(conn, "అమ్మ చెట్టు మీద వెళ్ళింది", path="/docs/far.pdf")

        assert _found(storage, "అమ్మ వెళ్ళింది", "proximity", distance=1) == [("amma", "అమ్మ ఇంటికి వెళ్ళింది")]
        assert {n for n, _ in _found(storage, "అమ్మ వెళ్ళింది", "proximity", distance=2)} == {
            "amma",
            "far",
        }

    def test_fuzzy_finds_a_misread_sign(self, storage, pages):
        # కాకీ has a long ee-sign where the page has the short one.
        assert _found(storage, "కాకీ", "fuzzy", threshold="loose") == [("kaki", "కాకి")]

    def test_fuzzy_does_not_confuse_a_word_with_its_consonants(self, storage, pages):
        assert _found(storage, "కాకి", "fuzzy", threshold="strict") == [("kaki", "కాకి")]

    def test_a_telugu_query_does_not_find_english_pages_or_the_reverse(self, storage, pages):
        assert _found(storage, "Museum", "like") == [("english", "Museum")]
        assert _found(storage, "Museum", "full-text") == [("english", "Museum")]
        assert _found(storage, "కాకి", "full-text") != [("english", ENGLISH)]

    def test_english_full_text_still_stems(self, storage, pages):
        assert _found(storage, "museums", "full-text") == [("english", "Museum")]


class TestDigits:
    def test_the_default_reads_the_digits_as_written(self, storage, pages):
        assert _found(storage, "2024", "like") == []
        assert _found(storage, "౨౦౨౪", "like") == [("year", "౨౦౨౪")]

    def test_folding_finds_telugu_digits_from_ascii_ones(self, storage, pages):
        assert _found(storage, "2024", "like", unicode="full") == [("year", "౨౦౨౪")]
        assert _found(storage, "2024", "fuzzy") == [("year", "౨౦౨౪")]
        assert _found(storage, "2024", "noise-fuzzy") == [("year", "౨౦౨౪")]

    def test_and_the_other_way_round(self, storage, conn, pages):
        SearchData.seed_page(conn, "Year 2024 report", path="/docs/ascii.pdf")
        Document.refresh_derived_text(conn, "pdf_pages")
        conn.commit()

        assert ("ascii", "2024") in _found(storage, "౨౦౨౪", "fuzzy")


class TestMixedQueries:
    def test_a_mixed_query_uses_the_telugu_aware_index(self, storage, conn):
        SearchData.seed_page(conn, "invoice అమ్మ ఇంటికి", path="/docs/mixed.pdf")

        assert [n for n, _ in _found(storage, "invoice అమ్మ", "full-text")] == [
            "mixed",
            "mixed",
        ]

    def test_english_words_on_a_telugu_page_are_not_stemmed_there(self, storage, conn):
        SearchData.seed_page(conn, "invoice అమ్మ", path="/docs/mixed.pdf")

        assert _found(storage, "invoices అమ్మ", "full-text") == []

    def test_an_english_query_still_stems_on_the_same_page(self, storage, conn):
        SearchData.seed_page(conn, "invoice అమ్మ", path="/docs/mixed.pdf")

        assert [n for n, _ in _found(storage, "invoices", "full-text")] == ["mixed"]


class TestWithoutTheMarkAwareIndex:
    @pytest.fixture
    def old_sqlite(self, monkeypatch):
        monkeypatch.setattr(SqliteStorage, "has_complex_word_index", lambda self: False)

    def test_telugu_full_text_says_why_instead_of_matching_fragments(
        self, storage, pages, old_sqlite
    ):
        with pytest.raises(SearchEngineUnavailable, match="newer SQLite"):
            Search.indexed_content(storage, "కాకి", engine="full-text")

    def test_telugu_proximity_says_why_too(self, storage, pages, old_sqlite):
        with pytest.raises(SearchEngineUnavailable):
            Search.indexed_content(storage, "అమ్మ వెళ్ళింది", engine="proximity")

    def test_the_combined_search_skips_those_engines_and_still_finds_the_text(
        self, storage, pages, old_sqlite
    ):
        results = Search.indexed_pages(storage, "కాకి")

        assert [r.file_name for r in results] == ["kaki.pdf"]
        assert "full-text" not in {e for r in results for e in r.matched_by}

    def test_like_and_fuzzy_are_unaffected(self, storage, pages, old_sqlite):
        assert _found(storage, "కాకి", "like") == [("kaki", "కాకి")]
        assert _found(storage, "కాకి", "fuzzy") == [("kaki", "కాకి")]

    def test_english_full_text_is_unaffected(self, storage, pages, old_sqlite):
        assert _found(storage, "museum", "full-text") == [("english", "Museum")]


class TestProximityTokens:
    def test_plain_words_are_cut_at_every_sign_as_the_plain_index_does(self):
        assert len(ProximitySearchEngine.token_starts("కాకి అమ్మ")) > 2

    def test_mark_aware_words_keep_their_signs(self):
        assert ProximitySearchEngine.token_starts("కాకి అమ్మ", True) == [0, 5]

    def test_english_tokens_are_the_same_either_way(self):
        text = "one two, three_four 5"

        assert ProximitySearchEngine.token_starts(text, True) == ProximitySearchEngine.token_starts(
            text
        )

    def test_clusters_count_telugu_words(self):
        text = "అమ్మ ఇంటికి వెళ్ళింది"
        spans = [[(0, 4)], [(12, 21)]]

        assert ProximitySearchEngine.find_clusters(text, spans, 1, True) == [(0, 21)]
        assert ProximitySearchEngine.find_clusters(text, spans, 0, True) == []
        # Read as the plain index reads it, the signs would count as words: too far apart.
        assert ProximitySearchEngine.find_clusters(text, spans, 1, False) == []


class TestSnippetContext:
    def test_context_does_not_start_on_a_sign(self):
        text = "అమ్మ ఇంటికి వెళ్ళింది"
        start = text.index("ఇంటికి")

        match = SearchEngineHelpers.build_match(
            document_id=1,
            file_path="/a.pdf",
            page_number=1,
            total_pages=1,
            duplicate_of_path=None,
            source="ocr",
            text=text,
            start=start,
            end=start + 6,
            chars=1,
            engine="like",
        )

        # One character of context before `ఇంటికి` is the space; two would be inside `అమ్మ`.
        assert match.before == " "

    def test_context_keeps_the_sign_of_the_last_letter(self):
        text = "కాకి"

        match = SearchEngineHelpers.build_match(
            document_id=1,
            file_path="/a.pdf",
            page_number=1,
            total_pages=1,
            duplicate_of_path=None,
            source="ocr",
            text=text,
            start=0,
            end=1,
            chars=1,
            engine="like",
        )

        assert match.matched == "క"
        assert match.after == "ా"

    def test_context_never_ends_between_a_letter_and_its_signs(self):
        text = "అమ్మ ఇంటికి వెళ్ళింది"

        for chars in range(0, 8):
            match = SearchEngineHelpers.build_match(
                document_id=1,
                file_path="/a.pdf",
                page_number=1,
                total_pages=1,
                duplicate_of_path=None,
                source="ocr",
                text=text,
                start=5,
                end=11,
                chars=chars,
                engine="like",
            )
            assert not match.before or not _is_sign(match.before[0])
            assert not match.after.startswith(("ా", "ి", "్"))

    def test_other_text_is_cut_exactly_where_it_always_was(self):
        match = SearchEngineHelpers.build_match(
            document_id=1,
            file_path="/a.pdf",
            page_number=1,
            total_pages=1,
            duplicate_of_path=None,
            source="ocr",
            text="résumé plus",
            start=2,
            end=6,
            chars=1,
            engine="like",
        )

        assert match.before == "e" and match.after == "e"


def _is_sign(char: str) -> bool:
    return char in "ాిీుూృౄెేైొోౌ్ంఃఁ"


def test_the_full_text_engine_has_the_parse_terms_it_always_had_for_english():
    assert FullTextSearchEngine.parse_terms("Hello World") == ['"Hello"', '"World"']
