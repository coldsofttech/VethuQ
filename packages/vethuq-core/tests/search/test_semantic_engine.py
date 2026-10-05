import pytest
from search_data import SearchData
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines import SearchEngines, SearchEngineUnavailable
from vethuq_core.search.engines.hybrid import HybridSearchEngine
from vethuq_core.search.engines.semantic import SemanticSearchEngine
from vethuq_core.semantic import Chunker, Embedders, SemanticModelError
from vethuq_core.settings import SearchSettings

POLICY = "Customers may return goods within thirty days for a full reimbursement."
MUSEUM = "The museum opens at nine every morning."


def _found(storage, query, **kwargs):
    return Search.indexed_content(storage, query, engine="semantic", **kwargs)


@pytest.fixture
def pages(conn):
    SearchData.seed_page(conn, POLICY, "/docs/policy.pdf")
    SearchData.seed_page(conn, MUSEUM, "/docs/museum.pdf")
    SearchData.seed_page(conn, "Lunch is served in the cafeteria.", "/docs/lunch.pdf")


class TestSemanticEngine:
    def test_finds_text_that_means_the_same_without_sharing_its_words(
        self, storage, embedder, pages
    ):
        matches = _found(storage, "refund policy", threshold=0.4)

        assert [m.file_name for m in matches] == ["policy.pdf"]
        assert matches[0].matched == POLICY
        assert matches[0].engine == "semantic"
        assert matches[0].score is not None and matches[0].score > 0.4

    def test_the_other_engines_cannot_find_it(self, storage, embedder, pages):
        assert Search.indexed_content(storage, "refund", engine="full-text") == []
        assert len(_found(storage, "refund", threshold=0.3)) == 1

    def test_finds_a_telugu_query_in_an_english_page(self, storage, embedder, pages):
        matches = _found(storage, "వాపసు", threshold=0.4)
        assert [m.file_name for m in matches] == ["policy.pdf"]

    def test_the_threshold_decides_what_counts(self, storage, embedder, pages):
        assert _found(storage, "refund policy", threshold=0.99) == []
        assert len(_found(storage, "refund policy", threshold=0.3)) >= 1

    def test_threshold_defaults_to_the_setting(self, storage, embedder, pages):
        SearchSettings.set_semantic_threshold(storage, "0.99")
        assert _found(storage, "refund policy") == []
        SearchSettings.set_semantic_threshold(storage, "0.3")
        assert len(_found(storage, "refund policy")) >= 1

    def test_pages_are_ordered_by_their_best_passage(self, conn, storage, embedder):
        SearchData.seed_page(conn, "A refund. Policy.", "/docs/weak.pdf")
        SearchData.seed_page(conn, "reimbursement refund repayment", "/docs/strong.pdf")

        matches = _found(storage, "refund", threshold=0.2)

        assert [m.file_name for m in matches] == ["strong.pdf", "weak.pdf"]
        assert matches[0].score >= matches[1].score

    def test_the_limit_caps_the_pages_returned(self, conn, storage, embedder):
        for number in range(5):
            SearchData.seed_page(conn, f"Refund number {number}.", f"/docs/{number}.pdf")
        SearchSettings.set_semantic_limit(storage, 2)

        assert len(_found(storage, "refund", threshold=0.2)) == 2

    def test_a_page_shows_its_best_passages_in_text_order(
        self, conn, storage, embedder, monkeypatch
    ):
        sentences = [
            "Refund the first order.",
            "Nothing else happens here at all today.",
            "Reimbursement of the second order.",
            "Nothing else happens here either way.",
            "Repayment of the third order.",
            "A fourth refund follows after that.",
        ]
        SearchData.seed_page(conn, " ".join(sentences), "/docs/long.pdf")
        monkeypatch.setattr(Chunker, "MAX_CHARS", 40)  # one passage per sentence

        matches = _found(storage, "refund", threshold=0.2)

        assert len(matches) == SemanticSearchEngine.MAX_HITS_PER_PAGE
        assert [m.start for m in matches] == sorted(m.start for m in matches)

    def test_snippets_carry_context_and_page_details(self, conn, storage, embedder):
        source = SearchData.add_source(conn, "/s")
        document = SearchData.add_document(conn, source, "/s/book.pdf")
        SearchData.add_pdf_page(conn, document, 1, "Intro text here. " * 3)
        SearchData.add_pdf_page(conn, document, 2, "Customers get a refund. Then goodbye.")

        (match,) = _found(storage, "refund", threshold=0.2, context_chars=5)

        assert (match.page_number, match.total_pages) == (2, 2)
        assert match.matched == "Customers get a refund. Then goodbye."
        assert match.before == "" and not match.truncated_before
        assert match.source == "ocr"

    def test_image_pages_are_searched_too(self, conn, storage, embedder):
        source = SearchData.add_source(conn, "/s")
        document = SearchData.add_document(conn, source, "/s/scan.png", file_type="image")
        SearchData.add_image_page(conn, document, "The invoice and the bill are attached.")

        (match,) = _found(storage, "receipt", threshold=0.2)

        assert (match.file_name, match.page_number) == ("scan.png", None)

    def test_a_duplicate_file_is_its_own_result(self, conn, storage, embedder):
        source = SearchData.add_source(conn, "/s")
        carrier = SearchData.add_document(conn, source, "/s/a.pdf")
        SearchData.add_pdf_page(conn, carrier, 1, POLICY)
        logical = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (carrier,)
        ).fetchone()[0]
        SearchData.add_document(conn, source, "/s/copy.pdf", document_id=logical)

        matches = _found(storage, "refund", threshold=0.2)

        assert sorted(m.file_name for m in matches) == ["a.pdf", "copy.pdf"]
        copy = next(m for m in matches if m.file_name == "copy.pdf")
        assert copy.duplicate_of_path == "/s/a.pdf"

    def test_pages_are_indexed_on_the_first_search(self, conn, storage, embedder, pages):
        assert embedder.passages == []
        _found(storage, "refund")
        assert len(embedder.passages) == 3
        _found(storage, "refund")
        assert len(embedder.passages) == 3

    def test_without_auto_index_only_embedded_pages_are_searched(self, storage, embedder, pages):
        engine = SemanticSearchEngine(storage, auto_index=False)
        assert engine.search("refund", threshold=0.2) == []
        assert embedder.passages == []

    def test_an_empty_query_matches_nothing(self, storage, embedder, pages):
        assert _found(storage, "") == []
        assert _found(storage, "   ") == []
        assert embedder.queries == []

    def test_an_empty_collection_matches_nothing(self, storage, embedder):
        assert _found(storage, "refund") == []

    def test_a_model_that_cannot_load_makes_the_engine_unavailable(self, storage, pages):
        def refuse():
            raise SemanticModelError("The model is not downloaded")

        Embedders.use(refuse)
        try:
            with pytest.raises(SearchEngineUnavailable, match="not downloaded"):
                _found(storage, "refund")
        finally:
            Embedders.use(None)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"case_sensitive": True}, "case-insensitive"),
            ({"distance": 3}, "no word distance"),
            ({"level": "basic"}, "no leetspeak level"),
            ({"noise": "low"}, "no noise level"),
            ({"unicode": "full"}, "no unicode setting"),
        ],
    )
    def test_options_it_cannot_honour_are_rejected(self, storage, embedder, kwargs, message):
        with pytest.raises(ValueError, match=message):
            SemanticSearchEngine(storage).search("refund", **kwargs)

    def test_an_invalid_threshold_is_rejected(self, storage, embedder):
        with pytest.raises(ValueError, match="threshold"):
            SemanticSearchEngine(storage).search("refund", threshold="nonsense")

    def test_the_query_and_passages_are_embedded_as_what_they_are(self, storage, embedder, pages):
        _found(storage, "refund policy")
        assert embedder.queries == ["refund policy"]
        assert POLICY in embedder.passages


class TestRegistry:
    def test_semantic_is_registered_and_listed(self, storage):
        assert "semantic" in SearchEngines.available()
        assert SearchEngines.get(storage, "semantic").name == "semantic"

    def test_it_is_a_plain_semantic_engine_unless_combined(self, storage):
        assert isinstance(SearchEngines.get(storage, "semantic"), SemanticSearchEngine)

    @pytest.mark.parametrize("partner", ["full-text", "lexical"])
    def test_combine_wraps_it_with_the_chosen_engine(self, storage, partner):
        SearchSettings.set_semantic_combine(storage, partner)
        engine = SearchEngines.get(storage, "semantic")
        assert isinstance(engine, HybridSearchEngine)
        assert engine.name == "semantic"

    def test_a_disabled_partner_means_semantic_alone(self, storage, monkeypatch):
        from vethuq_core.search.engines.catalog import SearchEngineCatalog

        SearchSettings.set_semantic_combine(storage, "lexical")
        monkeypatch.setattr(
            SearchEngineCatalog, "is_name_enabled", staticmethod(lambda name: name != "lexical")
        )
        assert isinstance(SearchEngines.get(storage, "semantic"), SemanticSearchEngine)


class TestOptions:
    def test_semantic_resolves_its_own_threshold(self, storage):
        options = Search.resolve_options(storage, "semantic", None)
        assert options == ("semantic", False, 0.8, None, None, None, None)

    def test_an_explicit_threshold_is_a_semantic_one(self, storage):
        assert (
            Search.resolve_options(storage, "semantic", None, threshold="strict").threshold == 0.86
        )
        assert Search.resolve_options(storage, "semantic", None, threshold="0.7").threshold == 0.7

    def test_the_setting_sets_the_default_threshold(self, storage):
        SearchSettings.set_semantic_threshold(storage, "loose")
        assert Search.resolve_options(storage, "semantic", None).threshold == 0.75

    def test_fuzzy_keeps_its_own_presets(self, storage):
        assert Search.resolve_options(storage, "fuzzy", None, threshold="strict").threshold == 0.9

    def test_case_sensitive_is_refused(self, storage):
        with pytest.raises(SearchOptionError) as excinfo:
            Search.resolve_options(storage, "semantic", True)
        assert excinfo.value.option == "case_sensitive"

    @pytest.mark.parametrize(
        ("kwargs", "option"),
        [
            ({"distance": 3}, "distance"),
            ({"noise": "low"}, "noise"),
            ({"unicode": "full"}, "unicode"),
        ],
    )
    def test_other_engines_options_are_refused(self, storage, kwargs, option):
        with pytest.raises(SearchOptionError) as excinfo:
            Search.resolve_options(storage, "semantic", None, **kwargs)
        assert excinfo.value.option == option

    def test_a_bad_threshold_names_the_option(self, storage):
        with pytest.raises(SearchOptionError) as excinfo:
            Search.resolve_options(storage, "semantic", None, threshold="nope")
        assert excinfo.value.option == "threshold"

    def test_all_does_not_run_semantic(self, storage, embedder, conn):
        SearchData.seed_page(conn, POLICY)
        Search.indexed_pages(storage, "refund")
        assert embedder.queries == []
