import sqlite3

from search_data import SearchData
from vethuq_core.search import PageResult, Search
from vethuq_core.search.engines import Ranking
from vethuq_core.storage import Storage


class TestRanking:
    @staticmethod
    def _pages(storage: Storage, query: str, **kwargs) -> dict[str, PageResult]:
        return {page.file_name: page for page in Search.indexed_pages(storage, query, **kwargs)}

    def test_tiers_and_badges(self):
        assert Ranking.TIERS == (
            "exact",
            "like",
            "lexical",
            "proximity",
            "full-text",
            "leetspeak",
            "fuzzy",
        )
        assert [Ranking.BADGES[e] for e in Ranking.TIERS] == [
            "Exact",
            "Contains",
            "Relevant",
            "Near",
            "Word",
            "Lookalike",
            "Similar",
        ]
        assert Ranking.engine_rank("exact") < Ranking.engine_rank("like")
        assert Ranking.engine_rank("like") < Ranking.engine_rank("fuzzy")
        assert Ranking.engine_badge("fuzzy", 0.83) == "Similar 83%"
        assert Ranking.engine_badge("fuzzy") == "Similar"
        assert Ranking.engine_badge("exact", 1.0) == "Exact"  # only Similar shows a figure

    def test_pages_are_ranked_by_the_strictest_engine_that_found_them(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "paymnt terminaton clause", "/d/e_similar.pdf")
        SearchData.seed_page(conn, "payment " + "filler " * 30 + "termination", "/d/d_word.pdf")
        SearchData.seed_page(
            conn, "payment is due, subject to the termination clause", "/d/c_near.pdf"
        )
        SearchData.seed_page(conn, "the Payment Termination clause", "/d/b_contains.pdf")
        SearchData.seed_page(conn, "the payment termination clause", "/d/a_exact.pdf")

        pages = Search.indexed_pages(storage, "payment termination")

        assert [(p.file_name, p.engine) for p in pages] == [
            ("a_exact.pdf", "exact"),
            ("b_contains.pdf", "like"),
            ("c_near.pdf", "proximity"),
            ("d_word.pdf", "full-text"),
            ("e_similar.pdf", "fuzzy"),
        ]

    def test_a_lookalike_page_ranks_below_the_real_word_and_above_a_typo(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "say Hello to all", "/d/d_word.pdf")
        SearchData.seed_page(conn, "say h3ll0 to all", "/d/c_lookalike.pdf")
        SearchData.seed_page(conn, "say hellp to all", "/d/e_similar.pdf")
        SearchData.seed_page(conn, "say hello to all", "/d/a_exact.pdf")

        pages = Search.indexed_pages(storage, "hello")

        assert [(p.file_name, p.engine) for p in pages] == [
            ("a_exact.pdf", "exact"),
            ("d_word.pdf", "like"),
            ("c_lookalike.pdf", "leetspeak"),
            ("e_similar.pdf", "fuzzy"),
        ]
        lookalike = next(p for p in pages if p.engine == "leetspeak")
        assert lookalike.matched_by == ("leetspeak",)
        (hit,) = lookalike.hits
        assert (hit.matched, Ranking.hit_badge(hit)) == ("h3ll0", "Lookalike")

    def test_a_disguised_word_is_found_by_a_plain_query_and_the_other_way_round(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the p@55w0rd is secret", "/d/a.pdf")
        SearchData.seed_page(conn, "the password is secret", "/d/b.pdf")

        plain = TestRanking._pages(storage, "password")
        disguised = TestRanking._pages(storage, "p@55w0rd")

        assert (plain["b.pdf"].engine, plain["a.pdf"].engine) == ("exact", "leetspeak")
        assert (disguised["a.pdf"].engine, disguised["b.pdf"].engine) == ("exact", "leetspeak")

    def test_lookalike_pages_order_by_how_much_was_disguised(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "p@55w0rd", "/d/a_more.pdf")
        SearchData.seed_page(conn, "p@ssword", "/d/z_less.pdf")

        pages = Search.indexed_pages(storage, "password")

        assert [(p.file_name, p.engine) for p in pages] == [
            ("z_less.pdf", "leetspeak"),
            ("a_more.pdf", "leetspeak"),
        ]
        assert pages[0].score > pages[1].score

    def test_a_query_too_short_for_leetspeak_is_skipped_without_failing(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "go to the museum", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "go")

        assert "leetspeak" not in page.matched_by

    def test_a_page_is_one_result_listing_every_engine_that_found_it(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the payment termination clause", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "payment termination")

        assert page.engine == "exact"
        assert page.matched_by == (
            "exact",
            "like",
            "lexical",
            "proximity",
            "full-text",
            "leetspeak",
            "fuzzy",
        )

    def test_engines_finding_the_same_words_give_one_hit_labelled_by_the_strictest(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Visit the Museum today", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "Museum")

        (hit,) = page.hits
        assert (hit.engine, hit.matched) == ("exact", "Museum")
        # one word, so proximity had nothing to do and was skipped without failing the search
        assert hit.matched_by == ("exact", "like", "lexical", "full-text", "leetspeak", "fuzzy")
        assert Ranking.hit_badge(hit) == "Exact"

    def test_different_words_stay_separate_hits_best_first(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the Muzeum guide, and later the Museum shop", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "Museum")

        assert [(h.matched, h.engine) for h in page.hits] == [
            ("Museum", "exact"),
            ("Muzeum", "fuzzy"),
        ]
        assert Ranking.hit_badge(page.hits[1]) == "Similar 83%"
        assert page.matched_by == ("exact", "like", "lexical", "full-text", "leetspeak", "fuzzy")

    def test_hits_that_overlap_merge_into_their_union(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        # `like` finds "museum" inside "museums" while `full-text` and `fuzzy` find the whole word.
        SearchData.seed_page(conn, "two museums here", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "museum")

        (hit,) = page.hits
        assert (hit.matched, hit.engine) == ("museums", "like")
        assert hit.matched_by == ("like", "lexical", "full-text", "fuzzy")
        assert (hit.before, hit.after) == ("two ", " here")
        assert page.engine == "like"

    def test_a_proximity_passage_absorbs_the_word_hits_inside_it(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(
            conn,
            "the payment is due within thirty days, subject to the termination clause",
            "/d/a.pdf",
        )

        (page,) = Search.indexed_pages(storage, "payment termination", context_chars=4)

        (hit,) = page.hits
        assert hit.engine == "proximity"
        assert hit.matched == "payment is due within thirty days, subject to the termination"
        assert hit.matched_by == ("proximity", "full-text", "fuzzy")
        assert (hit.before, hit.after) == ("the ", " cla")

    def test_hits_are_ordered_by_engine_then_position(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Muzeum first, then the Museum, then Muzeum again", "/d/a.pdf")

        (page,) = Search.indexed_pages(storage, "Museum")

        assert [(h.matched, h.engine) for h in page.hits] == [
            ("Museum", "exact"),
            ("Muzeum", "fuzzy"),
            ("Muzeum", "fuzzy"),
        ]
        assert (page.hits[1].start or 0) < (page.hits[2].start or 0)

    def test_within_a_tier_exact_and_contains_order_by_number_of_hits(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the Museum", "/d/a_one.pdf")
        SearchData.seed_page(conn, "the Museum and the Museum and the Museum", "/d/z_three.pdf")

        pages = Search.indexed_pages(storage, "Museum")

        assert [p.file_name for p in pages] == ["z_three.pdf", "a_one.pdf"]
        assert [p.score for p in pages] == [3.0, 1.0]

    def test_within_the_word_tier_pages_order_by_relevance(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        # "running" is matched by full-text alone: it stems to the same word as "runs"
        SearchData.seed_page(conn, "he runs " + "filler " * 40, "/d/a_weak.pdf")
        SearchData.seed_page(conn, "runs runs runs runs " + "filler " * 10, "/d/z_strong.pdf")

        pages = Search.indexed_pages(storage, "running")

        assert [(p.file_name, p.engine) for p in pages] == [
            ("z_strong.pdf", "full-text"),
            ("a_weak.pdf", "full-text"),
        ]
        assert pages[0].score > pages[1].score

    def test_within_the_similar_tier_pages_order_by_closeness(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the muzeum guide", "/d/a_close.pdf")  # 83%
        SearchData.seed_page(conn, "the museu guide", "/d/b_closer.pdf")  # 83%, other edit
        SearchData.seed_page(conn, "the musem guides and museum", "/d/z_exact.pdf")

        pages = Search.indexed_pages(storage, "museum")

        assert pages[0].file_name == "z_exact.pdf"
        assert {p.engine for p in pages[1:]} == {"fuzzy"}
        assert all(0.8 <= p.score <= 1 for p in pages[1:])

    def test_agreement_breaks_ties(self, conn: sqlite3.Connection, storage: Storage):
        # Both pages are Contains-tier with one hit; only one is also found by
        # full-text, leetspeak and fuzzy (and, with `like`, by lexical).
        SearchData.seed_page(conn, "the museumgoers", "/d/a_alone.pdf")
        SearchData.seed_page(conn, "the Museum", "/d/z_agreed.pdf")

        pages = Search.indexed_pages(storage, "museum")

        assert [(p.file_name, p.engine, len(p.matched_by)) for p in pages] == [
            ("z_agreed.pdf", "like", 5),
            ("a_alone.pdf", "like", 2),
        ]

    def test_case_sensitive_reaches_like_and_fuzzy_but_never_breaks_the_others(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the MUSEUM", "/d/a.pdf")

        loose = TestRanking._pages(storage, "museum")
        strict = TestRanking._pages(storage, "museum", case_sensitive=True)

        assert loose["a.pdf"].engine == "like"
        # like and fuzzy now insist on case; full-text still finds the word
        assert strict["a.pdf"].engine == "full-text"
        assert strict["a.pdf"].matched_by == ("full-text",)

    def test_threshold_and_distance_reach_their_engines(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the Museurn shop", "/d/a.pdf")
        SearchData.seed_page(conn, "payment " + "w " * 20 + "termination", "/d/b.pdf")

        assert TestRanking._pages(storage, "Museum") == {}
        assert TestRanking._pages(storage, "Museum", threshold=0.65)["a.pdf"].engine == "fuzzy"
        near = TestRanking._pages(storage, "payment termination", distance=30)["b.pdf"]
        assert near.engine == "proximity"
        assert TestRanking._pages(storage, "payment termination")["b.pdf"].engine == "full-text"

    def test_no_matches_and_blank_queries(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "nothing relevant here", "/d/a.pdf")

        assert Search.indexed_pages(storage, "zebra") == []
        assert Search.indexed_pages(storage, "") == []
        assert Search.indexed_pages(storage, "  ?! ") == []

    def test_a_duplicate_document_is_its_own_page_result(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "the payment termination clause", "/d/original.pdf")
        original = conn.execute("SELECT document_id, source_id FROM document_index").fetchone()
        SearchData.add_document(
            conn, original["source_id"], "/d/copy.pdf", document_id=original["document_id"]
        )

        pages = TestRanking._pages(storage, "payment termination")

        assert pages["original.pdf"].duplicate_of_path is None
        assert pages["copy.pdf"].duplicate_of_path == "/d/original.pdf"
        assert pages["copy.pdf"].engine == "exact"

    def test_indexed_content_all_returns_the_ranked_hits_flat(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Muzeum guide", "/d/b_similar.pdf")
        SearchData.seed_page(conn, "the Museum", "/d/a_exact.pdf")

        flat = Search.indexed_content(storage, "Museum", engine="all")

        assert [(m.file_name, m.engine) for m in flat] == [
            ("a_exact.pdf", "exact"),
            ("b_similar.pdf", "fuzzy"),
        ]
        assert flat == Ranking.flatten(Search.indexed_pages(storage, "Museum"))
        assert flat[0].matched_by[0] == "exact"

    def test_single_engine_matches_name_their_engine_and_position(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Visit the Museum today", "/d/a.pdf")

        for engine in ("like", "exact", "full-text", "leetspeak", "fuzzy"):
            (match,) = Search.indexed_content(storage, "Museum", engine=engine)
            assert match.engine == engine
            assert (match.start, match.end) == (10, 16)
            assert match.matched_by == ()  # only the combined search lists several

    def test_resolving_all_accepts_every_option(self, storage: Storage):
        options = Search.resolve_options(storage, "all", True, threshold="loose", distance="tight")

        assert options == ("all", True, 0.65, 3)
