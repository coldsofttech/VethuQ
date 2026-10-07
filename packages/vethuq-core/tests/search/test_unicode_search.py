"""A Unicode query finds Unicode matches in every engine: case, accents, CJK, Cyrillic and
composed vs decomposed forms."""

import unicodedata

import pytest
from search_data import SearchData
from vethuq_core.search import Search

ENGINES = ["exact", "fuzzy", "full-text", "like", "lexical"]
WORD_ENGINES = ["exact", "fuzzy", "full-text", "like"]

COMPOSED = "café"
DECOMPOSED = unicodedata.normalize("NFD", COMPOSED)


def _found(storage, query, engine, **options):
    return [m.matched for m in Search.indexed_content(storage, query, engine=engine, **options)]


def test_the_two_forms_differ_in_code_points():
    assert COMPOSED != DECOMPOSED
    assert len(COMPOSED) == 4 and len(DECOMPOSED) == 5


class TestEveryEngine:
    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize(
        ("text", "query"),
        [
            ("Visit the café on the corner", "café"),
            ("Ceny w złotych: żółć", "żółć"),
            ("Привет мир, добро пожаловать", "привет".capitalize()),
            ("Привет мир, добро пожаловать", "добро"),
            ("東京都の美術館を訪れる", "美術館"),
            ("東京都の美術館を訪れる", "東京都"),
            ("서울 국립 박물관", "박물관"),
        ],
    )
    def test_a_unicode_query_finds_the_match_unchanged(self, conn, storage, engine, text, query):
        if engine in ("exact", "fuzzy", "full-text") and not _spaced(text, query):
            pytest.skip("contiguous CJK has no word boundaries; covered by like and lexical")
        SearchData.seed_page(conn, text)

        assert _found(storage, query, engine) == [query]


def _spaced(text: str, query: str) -> bool:
    """Whether `query` is a whole whitespace/punctuation-delimited word of `text`."""
    return query in text.replace(",", " ").split()


class TestCaseInsensitive:
    @pytest.mark.parametrize("engine", ["like", "lexical", "full-text", "fuzzy"])
    @pytest.mark.parametrize(
        ("text", "query", "expected"),
        [
            ("ÉCOLE Normale", "école", "ÉCOLE"),
            ("école normale", "ÉCOLE", "école"),
            ("ПРИВЕТ мир", "привет", "ПРИВЕТ"),
            ("привет мир", "ПРИВЕТ", "привет"),
            ("Ελλάδα και Ελλάδα", "ΕΛΛΆΔΑ", "Ελλάδα"),
        ],
    )
    def test_finds_the_other_case(self, conn, storage, engine, text, query, expected):
        SearchData.seed_page(conn, text)

        assert _found(storage, query, engine)[0] == expected

    @pytest.mark.parametrize("engine", ["exact"])
    def test_exact_keeps_the_case(self, conn, storage, engine):
        SearchData.seed_page(conn, "ПРИВЕТ привет")

        assert _found(storage, "привет", engine) == ["привет"]
        assert _found(storage, "ПРИВЕТ", engine) == ["ПРИВЕТ"]

    def test_proximity_ignores_case(self, conn, storage):
        SearchData.seed_page(conn, "ÉCOLE de ПАРИЖ")

        (match,) = Search.indexed_content(storage, "école париж", engine="proximity", distance=5)
        assert "ÉCOLE" in match.matched and "ПАРИЖ" in match.matched


class TestAccents:
    @pytest.mark.parametrize("engine", ["like", "lexical", "exact"])
    def test_an_accent_is_kept_by_default(self, conn, storage, engine):
        SearchData.seed_page(conn, "a café and a cafe")

        assert _found(storage, "café", engine) == ["café"]
        assert _found(storage, "cafe", engine) == ["cafe"]

    def test_fuzzy_tolerates_a_missing_accent(self, conn, storage):
        SearchData.seed_page(conn, "a café and a cafe")

        assert _found(storage, "cafe", "fuzzy") == ["café", "cafe"]
        assert _found(storage, "café", "fuzzy") == ["café", "cafe"]

    @pytest.mark.parametrize("engine", ["like", "exact", "fuzzy"])
    def test_full_folds_accents_both_ways(self, conn, storage, engine):
        SearchData.seed_page(conn, "a café and a cafe")

        assert _found(storage, "cafe", engine, unicode="full") == ["café", "cafe"]
        assert _found(storage, "café", engine, unicode="full") == ["café", "cafe"]

    def test_full_text_folds_accents_by_default(self, conn, storage):
        SearchData.seed_page(conn, "a café and a cafe")

        assert _found(storage, "cafe", "full-text") == ["café", "cafe"]

    def test_proximity_matches_accented_words(self, conn, storage):
        SearchData.seed_page(conn, "Le café est près de la école")

        (match,) = Search.indexed_content(storage, "café école", engine="proximity", distance=8)
        assert "café" in match.matched and "école" in match.matched


class TestComposedAndDecomposed:
    @pytest.mark.parametrize("engine", WORD_ENGINES)
    def test_a_composed_query_finds_decomposed_text(self, conn, storage, engine):
        SearchData.seed_page(conn, f"a {DECOMPOSED} here")

        assert _found(storage, COMPOSED, engine) == [DECOMPOSED]

    @pytest.mark.parametrize("engine", WORD_ENGINES)
    def test_a_decomposed_query_finds_composed_text(self, conn, storage, engine):
        SearchData.seed_page(conn, f"a {COMPOSED} here")

        assert _found(storage, DECOMPOSED, engine) == [COMPOSED]

    def test_like_finds_a_substring_in_either_form(self, conn, storage):
        SearchData.seed_page(conn, f"x {DECOMPOSED}s and {COMPOSED}s")

        assert _found(storage, "café", "like") == [DECOMPOSED, COMPOSED]
        assert _found(storage, DECOMPOSED, "like") == [DECOMPOSED, COMPOSED]

    def test_lexical_matches_the_form_as_stored(self, conn, storage):
        SearchData.seed_page(conn, f"x {DECOMPOSED}s and {COMPOSED}s")

        assert _found(storage, COMPOSED, "lexical") == [COMPOSED]
        assert _found(storage, DECOMPOSED, "lexical") == [DECOMPOSED]

    @pytest.mark.xfail(
        strict=True, reason="the trigram index compares code points, so the forms do not meet"
    )
    def test_lexical_finds_the_other_form(self, conn, storage):
        SearchData.seed_page(conn, f"x {DECOMPOSED}s")

        assert _found(storage, COMPOSED, "lexical") == [DECOMPOSED]

    @pytest.mark.parametrize("engine", ["like", "exact"])
    def test_the_accent_is_not_dropped_by_composing(self, conn, storage, engine):
        SearchData.seed_page(conn, f"a {DECOMPOSED} and a cafe")

        assert _found(storage, "cafe", engine) == ["cafe"]

    @pytest.mark.parametrize("text_form", ["NFC", "NFD"])
    def test_proximity_finds_text_in_either_form_with_a_composed_query(
        self, conn, storage, text_form
    ):
        SearchData.seed_page(conn, unicodedata.normalize(text_form, "Le café est près de l'école"))

        assert Search.indexed_content(storage, "café école", engine="proximity", distance=8)

    @pytest.mark.xfail(
        strict=True, reason="an accent written as a separate mark ends the word for proximity"
    )
    @pytest.mark.parametrize(("query_form", "text_form"), [("NFD", "NFC"), ("NFD", "NFD")])
    def test_proximity_across_forms(self, conn, storage, query_form, text_form):
        SearchData.seed_page(conn, unicodedata.normalize(text_form, "Le café est près de l'école"))
        query = unicodedata.normalize(query_form, "café école")

        assert Search.indexed_content(storage, query, engine="proximity", distance=8)

    @pytest.mark.parametrize("engine", ["exact", "fuzzy", "like"])
    def test_hangul_and_cyrillic_forms_match_too(self, conn, storage, engine):
        decomposed_hangul = unicodedata.normalize("NFD", "한국어")
        decomposed_cyrillic = unicodedata.normalize("NFD", "Йод")
        SearchData.seed_page(conn, f"{decomposed_hangul} {decomposed_cyrillic}")

        assert _found(storage, "한국어", engine) == [decomposed_hangul]
        assert _found(storage, "Йод", engine) == [decomposed_cyrillic]

    @pytest.mark.xfail(
        strict=True, reason="the word index splits decomposed Hangul and Cyrillic marks"
    )
    def test_full_text_finds_decomposed_hangul(self, conn, storage):
        SearchData.seed_page(conn, unicodedata.normalize("NFD", "한국어 Йод"))

        assert _found(storage, "한국어", "full-text")


class TestProximityScripts:
    @pytest.mark.parametrize(
        ("text", "query"),
        [
            ("Привет прекрасный мир", "привет мир"),
            ("서울 국립 박물관", "서울 박물관"),
            ("Ceny w złotych: żółć", "ceny żółć"),
        ],
    )
    def test_finds_two_words_in_any_script(self, conn, storage, text, query):
        SearchData.seed_page(conn, text)

        (match,) = Search.indexed_content(storage, query, engine="proximity", distance=5)

        assert all(word.casefold() in match.matched.casefold() for word in query.split())
