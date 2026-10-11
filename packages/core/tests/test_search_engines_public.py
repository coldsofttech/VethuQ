"""Engine options, optional normalizers, ranking, `hybrid` and preparing pages (`Search.sync`)."""

from __future__ import annotations

import pytest

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq.enums import SearchSortBy
from vethuq.search import SearchSyncReport
from vethuq_addon_api import (
    AddonError,
    Hit,
    NormalizerUse,
    SearchEngine,
    SearchEngineSpec,
    SearchOption,
    SearchQueryError,
    SyncReport,
)


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def indexed(client, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    pages = {
        "museum.pdf": ["Visit the Museum today. Museums are open.", "Nothing"],
        "cafe.pdf": ["A café near the CAFE sign, h3ll0 there"],
        "refund.pdf": ["Customers may ask for a reimbursement within thirty days."],
        "guide.pdf": ["The museum guide explains the refund rules."],
    }
    for name, texts in pages.items():
        (root / name).write_text(fp.pdf_document(*(fp.native_page(t) for t in texts)))
    client.sources.create(root)
    assert client.index.run().status.value == "completed"
    return client


def install(client, monkeypatch, *specs, keep_others=True):
    catalog = client._search_catalog()
    others = list(catalog._specs()) if keep_others else []
    monkeypatch.setattr(catalog, "_specs", lambda: [*others, *specs])


def spec_of(client, engine_id):
    return next(s for s in client._search_catalog()._specs() if s.id == engine_id)


def names(result):
    return [(m.file_name, m.page_number, m.matched) for m in result]


class Finds(SearchEngine):
    """Finds each of `words` on every page, scoring a page by `score` (or not at all)."""

    def __init__(self, words, score=None, modifiers=(), seen=None):
        self.words, self.score, self.modifiers, self.seen = words, score, modifiers, seen

    def search(self, request, corpus):
        if self.seen is not None:
            self.seen.append(request)
        for page in corpus.candidates(None):
            for word in self.words:
                at = page.text.lower().find(word)
                if at != -1:
                    yield Hit(page, at, at + len(word), score=self.score, modifiers=self.modifiers)


class TestOptions:
    def test_an_engine_option_reaches_the_engine(self, indexed, monkeypatch):
        seen = []
        spec = SearchEngineSpec(
            "probe",
            "Probe",
            Finds(["museum"], seen=seen),
            options=(SearchOption("depth", default="1", choices=("1", "2")),),
        )
        install(indexed, monkeypatch, spec)
        indexed.search.run("x", engine="probe", options={"probe": {"depth": 2}})
        assert dict(seen[-1].options) == {"depth": "2"}
        indexed.search.run("x", engine="probe", options="probe.depth=1")
        assert dict(seen[-1].options) == {"depth": "1"}
        indexed.search.run("x", engine="probe")
        assert dict(seen[-1].options) == {}

    def test_options_go_only_to_their_engine(self, indexed, monkeypatch):
        seen_a, seen_b = [], []
        opt = (SearchOption("n"),)
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("a", "A", Finds(["museum"], seen=seen_a), options=opt),
            SearchEngineSpec("b", "B", Finds(["museum"], seen=seen_b), options=opt),
        )
        indexed.search.run("museum", options={"a": {"n": "1"}})
        assert dict(seen_a[-1].options) == {"n": "1"} and dict(seen_b[-1].options) == {}

    @pytest.mark.parametrize(
        ("options", "match"),
        [
            ({"nope": {"n": "1"}}, "no search engine 'nope'"),
            ({"probe": {"other": "1"}}, "no option 'other'"),
            ({"probe": {"depth": "9"}}, "must be one of 1, 2"),
            ({"like": {"depth": "1"}}, "isn't part of this search"),
            ({"like": "x"}, "must be a mapping"),
            ("probe.depth", "isn't ENGINE.OPTION=VALUE"),
            ("probe.depth=1,probe.depth=2", "given twice"),
        ],
    )
    def test_bad_options_are_refused(self, indexed, monkeypatch, options, match):
        spec = SearchEngineSpec(
            "probe",
            "Probe",
            Finds(["museum"]),
            options=(SearchOption("depth", choices=("1", "2")),),
        )
        install(indexed, monkeypatch, spec)
        with pytest.raises(errors.SearchOptionError, match=match):
            indexed.search.run("x", engine="probe", options=options)

    def test_an_engine_without_options_says_so(self, indexed):
        with pytest.raises(errors.SearchOptionError, match="has no options"):
            indexed.search.run("x", engine="like", options={"like": {"a": "1"}})

    def test_the_real_fuzzy_threshold_changes_what_is_found(self, indexed):
        loose = indexed.search.run("mxsexm", engine="fuzzy", options="fuzzy.threshold=loose")
        assert {m.matched.lower() for m in loose} == {"museum"}
        assert indexed.search.run("mxsexm", engine="fuzzy").total == 0
        with pytest.raises(errors.SearchQueryError, match="similarity"):
            indexed.search.run("museum", engine="fuzzy", options="fuzzy.threshold=wide")

    def test_the_real_proximity_distance_changes_what_is_found(self, indexed):
        assert indexed.search.run("museum rules", engine="proximity").total == 1
        assert (
            indexed.search.run(
                "museum rules", engine="proximity", options="proximity.distance=1"
            ).total
            == 0
        )

    def test_engines_report_their_options(self, indexed):
        info = {e.id: e for e in indexed.search.engines()}
        assert info["proximity"].options == {"distance": "medium"}
        assert set(info["noise-fuzzy"].options) == {"threshold", "leetspeak", "noise"}


class TestOptionalNormalizers:
    def test_leetspeak_is_an_option_of_like(self, indexed):
        assert indexed.search.run("hello", engine="like").total == 0
        found = indexed.search.run("hello", engine="like", normalize="leetspeak=basic")
        assert [m.matched for m in found] == ["h3ll0"]

    def test_a_search_works_without_the_normalizer_installed(self, indexed, monkeypatch):
        catalog = indexed._search_catalog()
        installed = catalog._normalizers
        monkeypatch.setattr(
            catalog, "_normalizers", lambda: [n for n in installed() if n.id != "leetspeak"]
        )
        like = next(e for e in indexed.search.engines() if e.id == "like")
        assert like.available and "leetspeak" not in like.normalizers
        assert indexed.search.run("museum", engine="like").total > 0
        with pytest.raises(errors.SearchOptionError, match="no normalizer 'leetspeak'"):
            indexed.search.run("hello", engine="like", normalize="leetspeak=basic")

    def test_a_required_normalizer_still_makes_an_engine_unavailable(self, indexed, monkeypatch):
        spec = SearchEngineSpec(
            "needy", "Needy", Finds(["museum"]), (NormalizerUse("ghost", "on"),)
        )
        install(indexed, monkeypatch, spec)
        needy = next(e for e in indexed.search.engines() if e.id == "needy")
        assert not needy.available and "ghost" in needy.reason


class TestMerging:
    def test_overlapping_hits_of_different_engines_are_one_match(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("wide", "Wide", Finds(["the museum guide"]), strictness=15),
            keep_others=False,
        )
        result = indexed.search.run("museum")
        assert len(result) == 1 and result[0].engine == "wide" and result[0].matched_by == ("wide",)

    def test_hits_of_one_engine_stay_separate_even_when_they_touch(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("touch", "Touch", Finds(["museum", "museums", "museum "])),
            keep_others=False,
        )
        result = indexed.search.run("x", engine="touch")
        assert len([m for m in result if m.file_name == "museum.pdf"]) == 3

    def test_a_merged_match_carries_the_best_score_and_every_modifier(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec(
                "a", "A", Finds(["museum"], score=0.4, modifiers=("accents",)), strictness=10
            ),
            SearchEngineSpec(
                "b", "B", Finds(["museum"], score=0.9, modifiers=("look-alike",)), strictness=20
            ),
            keep_others=False,
        )
        match = next(m for m in indexed.search.run("x") if m.file_name == "museum.pdf")
        assert match.engine == "a" and match.matched_by == ("a", "b")
        assert match.score == 0.9 and match.modifiers == ("accents", "look-alike")


class TestRank:
    def test_the_stricter_engine_ranks_first_and_modifiers_rank_lower(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("plain", "Plain", Finds(["refund"]), strictness=30),
            SearchEngineSpec(
                "shaky", "Shaky", Finds(["today"], modifiers=("accents",)), strictness=20
            ),
            SearchEngineSpec("guess", "Guess", Finds(["café"]), strictness=10, approximate=True),
            keep_others=False,
        )
        ranked = indexed.search.run("x", sort=SearchSortBy.RANK)
        engines = [m.engine for m in ranked]
        # as typed, then needing a normalization, then the approximate engine, whatever the numbers
        assert engines.index("plain") < engines.index("shaky") < engines.index("guess")

    def test_within_a_tier_the_engines_own_signal_orders_pages(self, indexed, monkeypatch):
        class Scored(SearchEngine):
            def search(self, request, corpus):
                for page in corpus.candidates(None):
                    if "museum" in page.text.lower():
                        score = 0.9 if page.text.startswith("The") else 0.2
                        yield Hit(page, 0, 3, score=score)

        install(indexed, monkeypatch, SearchEngineSpec("s", "S", Scored()), keep_others=False)
        ranked = indexed.search.run("x", sort="rank")
        assert [m.score for m in ranked] == [0.9, 0.2]
        assert [m.file_name for m in ranked] == ["guide.pdf", "museum.pdf"]

    def test_a_page_stays_together_in_text_order(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("w", "W", Finds(["museum", "today"], score=None)),
            keep_others=False,
        )
        ranked = indexed.search.run("x", sort="rank")
        by_page = [(m.file_name, m.page_number) for m in ranked]
        assert by_page == sorted(by_page, key=by_page.index)  # grouped
        page_one = [m for m in ranked if m.file_name == "museum.pdf"]
        assert [m.start for m in page_one] == sorted(m.start for m in page_one)

    def test_path_is_still_the_default_and_rank_can_be_reversed(self, indexed):
        default = indexed.search.run("museum", engine="like")
        keys = [(m.file_path, m.page_number, m.start) for m in default]
        assert keys == sorted(keys)
        ranked = indexed.search.run("museum", sort="rank", order="desc")
        assert ranked.total == indexed.search.run("museum", sort="rank").total

    def test_a_bad_sort_is_refused(self, indexed):
        with pytest.raises(ValueError):
            indexed.search.run("x", sort="best")


class TestHybrid:
    @staticmethod
    def engines(monkeypatch, client, *, keyword_fails=False, semantic_fails=False):
        class Meaning(SearchEngine):
            def search(self, request, corpus):
                if semantic_fails:
                    raise SearchQueryError("the model isn't ready")
                ranking = [("reimbursement", 0.95), ("refund", 0.85)]
                for page in corpus.candidates(None):
                    for word, score in ranking:
                        at = page.text.lower().find(word)
                        if at != -1:
                            yield Hit(page, 0, len(page.text), score=score)
                            break

        class Words(SearchEngine):
            def search(self, request, corpus):
                if keyword_fails:
                    raise SearchQueryError("needs two words")
                for page in corpus.candidates(None):
                    at = page.text.lower().find("refund")
                    if at != -1:
                        yield Hit(page, at, at + 6, score=3.0)
                    at = page.text.lower().find("museum")
                    if at != -1:
                        yield Hit(page, at, at + 6, score=2.0)

        install(
            client,
            monkeypatch,
            SearchEngineSpec(
                "semantic", "Semantic", Meaning(), in_all=False, strictness=80, approximate=True
            ),
            SearchEngineSpec("full-text", "Full-text", Words(), strictness=50),
            keep_others=False,
        )

    def test_both_engines_hits_are_shown_and_pages_fused(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed)
        result = indexed.search.run("refund", engine="hybrid")
        assert result.engine == "hybrid"
        # semantic ranks refund.pdf then guide.pdf; the keyword engine ranks guide.pdf then
        # museum.pdf (the best score first). guide.pdf is found by both, so it rises to the top.
        pages = list(dict.fromkeys(m.file_name for m in result))
        assert pages == ["guide.pdf", "refund.pdf", "museum.pdf"]
        by_engine = {(m.file_name, m.engine) for m in result}
        assert ("refund.pdf", "semantic") in by_engine and ("guide.pdf", "full-text") in by_engine
        # matched_by lists the engines that found the hit's page, strictest first
        assert {m.matched_by for m in result if m.file_name == "guide.pdf"} == {
            ("full-text", "semantic")
        }
        assert {m.matched_by for m in result if m.file_name == "refund.pdf"} == {("semantic",)}

    def test_hybrid_is_ranked_by_default(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed)
        result = indexed.search.run("refund", engine="hybrid")
        files = [m.file_name for m in result]
        assert files.index("guide.pdf") < files.index("refund.pdf") < files.index("museum.pdf")
        assert files == sorted(files, key=files.index)  # a page's matches stay together
        by_path = indexed.search.run("refund", engine="hybrid", sort="path")
        assert [m.file_path for m in by_path] == sorted(m.file_path for m in by_path)

    def test_hits_of_the_two_engines_are_not_merged(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed)
        result = indexed.search.run("refund", engine="hybrid")
        guide = [m for m in result if m.file_name == "guide.pdf"]
        # the passage semantic found, and the two words the keyword engine found inside it
        assert sorted(m.engine for m in guide) == ["full-text", "full-text", "semantic"]

    def test_the_keyword_engine_can_be_chosen_and_may_fail_quietly(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed, keyword_fails=True)
        result = indexed.search.run("refund", engine="hybrid", combine="full-text")
        assert {m.engine for m in result} == {"semantic"}

    def test_the_semantic_half_failing_fails_the_search(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed, semantic_fails=True)
        with pytest.raises(errors.SearchQueryError, match="isn't ready"):
            indexed.search.run("refund", engine="hybrid")

    def test_semantic_is_not_part_of_all(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed)
        assert {m.engine for m in indexed.search.run("refund")} == {"full-text"}

    def test_it_needs_semantic_and_a_keyword_engine(self, indexed, monkeypatch):
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("full-text", "FT", Finds(["x"])),
            keep_others=False,
        )
        with pytest.raises(errors.SearchUnavailableError, match="needs the semantic engine"):
            indexed.search.run("x", engine="hybrid")
        self.engines(monkeypatch, indexed)
        with pytest.raises(errors.SearchUnavailableError, match="needs the nope engine"):
            indexed.search.run("x", engine="hybrid", combine="nope")
        with pytest.raises(errors.SearchOptionError, match="keyword engine"):
            indexed.search.run("x", engine="hybrid", combine="semantic")

    def test_combine_belongs_to_hybrid(self, indexed):
        with pytest.raises(errors.SearchOptionError, match="only applies to the hybrid"):
            indexed.search.run("x", engine="like", combine="full-text")
        with pytest.raises(TypeError):
            indexed.search.run("x", engine="hybrid", combine=3)

    def test_hybrid_can_be_the_default_engine(self, indexed, monkeypatch):
        self.engines(monkeypatch, indexed)
        indexed.settings.search.set_engine("hybrid")
        assert indexed.search.run("refund").engine == "hybrid"

    def test_fusion_scores_by_position_only(self):
        from vethuq._search.ranking import _Fusion

        fused = _Fusion.scores({"a": {(1, 1): 9.0, (2, 1): 1.0}, "b": {(2, 1): 0.5, (3, 1): 0.1}})
        assert fused[(2, 1)] > fused[(1, 1)] > fused[(3, 1)]  # found by both beats best of one
        assert fused[(1, 1)] == pytest.approx(1 / 61)
        assert fused[(2, 1)] == pytest.approx(1 / 62 + 1 / 61)


class Preparing(SearchEngine):
    """An engine that must prepare pages before it can find them."""

    def __init__(self, result=None, error=None):
        self.ready = False
        self.result = result
        self.error = error
        self.progress = []

    def search(self, request, corpus):
        if self.ready:
            for page in corpus.candidates(None):
                yield Hit(page, 0, 1)

    def pending(self, corpus):
        return 0 if self.ready else sum(1 for _ in corpus.candidates(None))

    def sync(self, corpus, progress=None):
        if self.error:
            raise self.error
        total = sum(1 for _ in corpus.candidates(None))
        if progress:
            progress(total, total)
        self.ready = True
        return self.result or SyncReport(pages=total, charged_milli=1500)


class TestPreparing:
    def test_pending_pages_are_reported_by_a_search(self, indexed, monkeypatch):
        engine = Preparing()
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", engine), keep_others=False)
        result = indexed.search.run("x", engine="prep")
        assert result.total == 0 and result.pending == {"prep": 5}
        assert result.to_dict()["pending"] == {"prep": 5}

    def test_sync_prepares_and_reports(self, indexed, monkeypatch):
        engine = Preparing()
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", engine), keep_others=False)
        steps = []
        (report,) = indexed.search.sync("prep", progress=lambda e, d, t: steps.append((e, d, t)))
        assert isinstance(report, SearchSyncReport)
        assert (report.engine, report.pages, report.pending, report.credits) == ("prep", 5, 0, 1.5)
        assert not report.paused and steps == [("prep", 5, 5)]
        result = indexed.search.run("x", engine="prep")
        assert result.total == 5 and result.pending == {}

    def test_sync_without_a_name_asks_every_available_engine(self, indexed, monkeypatch):
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", Preparing()))
        reports = {r.engine: r for r in indexed.search.sync()}
        assert reports["prep"].pages == 5
        assert reports["like"].pages == 0 and reports["like"].pending == 0  # nothing to do

    def test_a_paused_sync_says_so(self, indexed, monkeypatch):
        engine = Preparing(
            SyncReport(pages=2, pending=3, charged_milli=1000, paused=True, message="out")
        )
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", engine), keep_others=False)
        (report,) = indexed.search.sync("prep")
        assert (report.paused, report.pending, report.message) == (True, 3, "out")
        assert report.to_dict()["credits"] == 1.0 and '"paused": true' in report.to_json()

    def test_a_named_engine_that_cannot_be_prepared_is_an_error(self, indexed, monkeypatch):
        engine = Preparing(error=AddonError("no model", "download it"))
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", engine), keep_others=False)
        with pytest.raises(errors.SearchUnavailableError, match="no model"):
            indexed.search.sync("prep")

    def test_without_a_name_one_engine_failing_does_not_stop_the_others(self, indexed, monkeypatch):
        bad = Preparing(error=AddonError("no model"))
        good = Preparing()
        install(
            indexed,
            monkeypatch,
            SearchEngineSpec("bad", "Bad", bad),
            SearchEngineSpec("good", "Good", good),
            keep_others=False,
        )
        reports = {r.engine: r for r in indexed.search.sync()}
        assert reports["bad"].message == "no model" and reports["good"].pages == 5

    def test_a_broken_engine_is_skipped_unless_named(self, indexed, monkeypatch):
        bad = Preparing(error=RuntimeError("boom"))
        install(indexed, monkeypatch, SearchEngineSpec("bad", "Bad", bad), keep_others=False)
        assert indexed.search.sync() == []
        with pytest.raises(RuntimeError):
            indexed.search.sync("bad")

    def test_unknown_engines_and_types(self, indexed):
        with pytest.raises(errors.SearchUnavailableError):
            indexed.search.sync("nope")
        with pytest.raises(TypeError):
            indexed.search.sync(3)

    def test_the_index_is_brought_up_to_date_first(self, indexed, monkeypatch):
        engine = Preparing()
        install(indexed, monkeypatch, SearchEngineSpec("prep", "Prep", engine), keep_others=False)
        indexed.search.rebuild()
        assert indexed.search.status().pages_indexed == indexed.search.status().pages_total
