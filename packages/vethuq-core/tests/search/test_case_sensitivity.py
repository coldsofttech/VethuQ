import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.storage import Storage


class TestCaseInsensitive:
    @pytest.mark.parametrize("engine", ["like", "full-text", "fuzzy"])
    def test_matches_regardless_of_case(self, conn, storage: Storage, engine: str):
        SearchData.seed_page(conn, "The MUSEUM opens; the Museum closes.")

        matches = Search.indexed_content(storage, "museum", engine=engine)

        assert [m.matched for m in matches] == ["MUSEUM", "Museum"]

    @pytest.mark.parametrize("engine", ["like", "full-text", "fuzzy"])
    def test_is_the_default(self, conn, storage: Storage, engine: str):
        SearchData.seed_page(conn, "Visit the Museum today")

        default = Search.indexed_content(storage, "museum", engine=engine)
        explicit = Search.indexed_content(storage, "museum", engine=engine, case_sensitive=False)

        assert [m.matched for m in default] == ["Museum"]
        assert default == explicit

    def test_fuzzy_scores_a_case_difference_as_identical(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        (match,) = Search.indexed_content(storage, "museum", engine="fuzzy")

        assert match.score == 1.0


class TestCaseSensitive:
    def test_like_only_matches_same_case(self, conn, storage: Storage):
        SearchData.seed_page(conn, "The Museum opens; the museum closes.")

        insensitive = Search.indexed_content(storage, "museum")
        sensitive = Search.indexed_content(storage, "museum", case_sensitive=True)

        assert [m.matched for m in insensitive] == ["Museum", "museum"]
        assert [m.matched for m in sensitive] == ["museum"]

    def test_like_finds_nothing_when_no_page_has_that_case(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert Search.indexed_content(storage, "museum", case_sensitive=True) == []

    def test_exact_is_always_case_sensitive(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert Search.indexed_content(storage, "museum", engine="exact") == []
        assert [m.matched for m in Search.indexed_content(storage, "Museum", engine="exact")] == [
            "Museum"
        ]

    def test_exact_ignores_an_explicit_case_insensitive_flag(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        matches = Search.indexed_content(storage, "museum", engine="exact", case_sensitive=False)

        assert matches == []

    def test_full_text_cannot_be_case_sensitive(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        with pytest.raises(ValueError, match="case-insensitive"):
            Search.indexed_content(storage, "museum", engine="full-text", case_sensitive=True)

    def test_fuzzy_counts_a_case_difference_as_one_edit(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        (match,) = Search.indexed_content(
            storage, "museum", engine="fuzzy", case_sensitive=True, threshold=0.8
        )
        stricter = Search.indexed_content(
            storage, "museum", engine="fuzzy", case_sensitive=True, threshold=0.9
        )

        assert match.matched == "Museum"
        assert match.score == pytest.approx(1 - 1 / 6)
        assert stricter == []
