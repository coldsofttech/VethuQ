import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.search.engines import SearchEngines
from vethuq_core.search.engines.hybrid import HybridSearchEngine
from vethuq_core.settings import SearchSettings


@pytest.fixture
def pages(conn):
    # `exact` has the word, `meaning` has only the idea, `both` has both.
    SearchData.seed_page(conn, "Please send the refund form.", "/docs/exact.pdf")
    SearchData.seed_page(conn, "Reimbursement of repayment arrives soon.", "/docs/meaning.pdf")
    SearchData.seed_page(conn, "Refund and reimbursement of the repayment.", "/docs/both.pdf")
    SearchData.seed_page(conn, "Nothing relevant here at all.", "/docs/none.pdf")


def _search(storage, query="refund", **kwargs):
    return Search.indexed_content(storage, query, engine="semantic", threshold=0.2, **kwargs)


class TestHybrid:
    def test_semantic_alone_misses_nothing_it_would_find_without_the_setting(
        self, storage, embedder, pages
    ):
        assert SearchSettings.get_semantic_combine(storage) == "off"
        names = {m.file_name for m in _search(storage)}
        assert names == {"exact.pdf", "meaning.pdf", "both.pdf"}

    @pytest.mark.parametrize("partner", ["full-text", "lexical"])
    def test_a_page_both_engines_find_ranks_first(self, storage, embedder, pages, partner):
        SearchSettings.set_semantic_combine(storage, partner)

        matches = _search(storage)

        order = list(dict.fromkeys(m.file_name for m in matches))
        assert order[0] == "both.pdf"
        assert set(order) == {"both.pdf", "exact.pdf", "meaning.pdf"}

    def test_hits_say_which_engine_found_them(self, storage, embedder, pages):
        SearchSettings.set_semantic_combine(storage, "full-text")

        matches = [m for m in _search(storage) if m.file_name == "both.pdf"]

        assert {m.engine for m in matches} == {"semantic", "full-text"}
        assert all(m.matched_by == ("semantic", "full-text") for m in matches)

    def test_a_page_only_one_engine_finds_says_so(self, storage, embedder, pages):
        SearchSettings.set_semantic_combine(storage, "full-text")

        matches = _search(storage)

        meaning = [m for m in matches if m.file_name == "meaning.pdf"]
        assert [m.engine for m in meaning] == ["semantic"]
        assert meaning[0].matched_by == ("semantic",)

    def test_a_keyword_engine_that_cannot_search_the_query_adds_nothing(
        self, storage, embedder, pages
    ):
        SearchSettings.set_semantic_combine(storage, "lexical")  # needs three characters

        matches = _search(storage, "re")

        assert all(m.engine == "semantic" for m in matches)

    def test_hits_within_a_page_are_in_text_order(self, storage, embedder, pages):
        SearchSettings.set_semantic_combine(storage, "full-text")

        starts = [m.start for m in _search(storage) if m.file_name == "both.pdf"]

        assert starts == sorted(starts)

    def test_the_engines_options_reach_the_semantic_engine(self, storage, embedder, pages):
        SearchSettings.set_semantic_combine(storage, "full-text")
        engine = SearchEngines.get(storage, "semantic")
        assert isinstance(engine, HybridSearchEngine)

        keyword_only = engine.search("refund", threshold=0.999)

        assert {m.engine for m in keyword_only} == {"full-text"}

    def test_options_a_semantic_engine_cannot_honour_still_fail(self, storage, embedder, pages):
        SearchSettings.set_semantic_combine(storage, "full-text")
        with pytest.raises(ValueError, match="case-insensitive"):
            SearchEngines.get(storage, "semantic").search("refund", case_sensitive=True)

    def test_reciprocal_rank_fusion_prefers_agreement_over_one_high_rank(self):
        # Constructed directly: A is first for one engine only, B is second for both.
        from vethuq_core.search.engines.base import SearchMatch

        def hit(file_id, engine):
            return SearchMatch(
                file_id=file_id,
                file_name=f"{file_id}",
                file_path=f"/{file_id}",
                page_number=1,
                total_pages=1,
                before="",
                matched="x",
                after="",
                truncated_before=False,
                truncated_after=False,
                duplicate_of_path=None,
                start=0,
                end=1,
                engine=engine,
            )

        class Stub:
            def __init__(self, name, matches):
                self.name = name
                self._matches = matches

            def search(self, query, **kwargs):
                return self._matches

        semantic = Stub("semantic", [hit(1, "semantic"), hit(2, "semantic")])
        keyword = Stub("full-text", [hit(3, "full-text"), hit(2, "full-text")])

        ordered = [m.file_id for m in HybridSearchEngine(semantic, keyword).search("q")]

        assert ordered == [2, 2, 1, 3]
