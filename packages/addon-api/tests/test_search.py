from __future__ import annotations

import pytest

from vethuq_addon_api import (
    API_VERSION,
    Addon,
    CreditsExhaustedError,
    Folded,
    Hit,
    Manifest,
    NormalizerUse,
    PageText,
    Pipeline,
    SearchEngine,
    SearchEngineSpec,
    SearchOption,
    SearchQueryError,
    SearchRequest,
    SyncReport,
)
from vethuq_addon_api.testing import FakeCorpus, FakeCredits, FakeHost, FakeNormalizer


class Shift(FakeNormalizer):
    """Drops every hyphen, so positions move."""

    def fold(self, text, level):
        if level == self.identity:
            return Folded(text)
        starts, ends, kept = [], [], []
        for i, char in enumerate(text):
            if char != "-":
                kept.append(char)
                starts.append(i)
                ends.append(i + 1)
        return Folded("".join(kept), starts, ends)


class TestFolded:
    def test_without_positions_a_span_is_the_same_span(self):
        assert Folded("abc").original(1, 2) == (1, 2)

    def test_with_positions_a_span_is_traced_back(self):
        folded = Shift("s").fold("a-b-c", "on")
        assert folded.text == "abc"
        assert folded.original(1, 3) == (2, 5)

    def test_an_empty_span(self):
        folded = Shift("s").fold("a-b", "on")
        assert folded.original(1, 1) == (2, 2)
        assert folded.original(2, 2) == (3, 3)

    def test_composing_two_folds_traces_to_the_original(self):
        first = Shift("s").fold("a-B-c", "on")
        second = FakeNormalizer().fold(first.text, "on")
        assert Folded.compose(first, second).original(0, 3) == (0, 5)
        assert Folded.compose(Folded("x"), second) is second


class TestPipeline:
    def test_applies_steps_in_order_and_traces_positions(self):
        pipeline = Pipeline([(Shift("shift"), "on"), (FakeNormalizer("case"), "on")])
        folded = pipeline.fold("A-B-C")
        assert folded.text == "abc" and folded.original(0, 3) == (0, 5)
        assert pipeline.levels == {"shift": "on", "case": "on"}

    def test_an_identity_pipeline_changes_nothing(self):
        pipeline = Pipeline([(FakeNormalizer(), "off")])
        assert pipeline.is_identity and pipeline.fold("ABC").text == "ABC"
        assert Pipeline().is_identity

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(ValueError, match="must be one of off, on"):
            Pipeline([(FakeNormalizer(), "huge")])

    def test_index_form_runs_every_normalizer_by_order(self):
        upper = FakeNormalizer("up", {"a": "A"}, order=1)
        lower = FakeNormalizer("low", order=2)
        assert Pipeline.index_form([lower, upper], "aB") == "ab"  # upper first, then lower


class TestEngineContract:
    class Echo(SearchEngine):
        def search(self, request, corpus):
            for page in corpus.candidates(request.query):
                if request.query == "boom":
                    raise SearchQueryError("no")
                at = page.text.find(request.query)
                if at >= 0:
                    yield Hit(page, at, at + len(request.query), score=1.0)

    def test_an_engine_reads_a_corpus(self):
        corpus = FakeCorpus(["hello world", "nothing"])
        request = SearchRequest("world", Pipeline())
        (hit,) = list(self.Echo().search(request, corpus))
        assert (hit.page.text, hit.start, hit.end) == ("hello world", 6, 11)
        assert corpus.queries == ["world"] and request.levels == {}

    def test_a_query_an_engine_cannot_search(self):
        with pytest.raises(SearchQueryError):
            list(self.Echo().search(SearchRequest("boom", Pipeline()), FakeCorpus(["x"])))

    def test_spec_defaults(self):
        spec = SearchEngineSpec("echo", "Echo", self.Echo(), (NormalizerUse("case", "ignore"),))
        assert spec.available and spec.in_all and spec.strictness == 100
        use = spec.normalizers[0]
        assert (use.fixed, use.stored) == (False, True)

    def test_page_text_and_hits_are_values(self):
        page = PageText(1, 2, 3, 4, "text")
        assert page.source == "ocr" and Hit(page, 0, 1).modifiers == ()


class TestAddonHooks:
    def test_the_hooks_return_nothing_by_default(self, tmp_path):
        class Plain(Addon):
            manifest = Manifest(id="plain", name="p", version="1.0.0")

        addon = Plain(FakeHost(tmp_path / "v.db"))
        assert addon.search_engines() == [] and addon.normalizers() == []

    def test_an_engine_spec_has_an_optional_badge(self):
        assert SearchEngineSpec("a", "A", None).badge == ""
        assert SearchEngineSpec("a", "A", None, badge="Exact").badge == "Exact"

    def test_the_api_version(self):
        assert API_VERSION == "0.9.0"


class TestSixthApi:
    class Plain(SearchEngine):
        def search(self, request, corpus):
            return iter(())

    def test_a_request_has_no_options_unless_it_is_given_some(self):
        assert SearchRequest("q", Pipeline()).options == {}
        assert SearchRequest("q", Pipeline(), {"threshold": "0.8"}).options["threshold"] == "0.8"

    def test_a_normalizer_use_is_required_unless_optional(self):
        assert NormalizerUse("case", "ignore").optional is False
        assert NormalizerUse("leetspeak", "off", optional=True).optional is True

    def test_an_engine_declares_its_options(self):
        option = SearchOption("threshold", "how close", default="0.8", choices=("0.7", "0.8"))
        spec = SearchEngineSpec("fuzzy", "Fuzzy", self.Plain(), options=(option,))
        assert spec.options[0].name == "threshold" and SearchOption("x").choices == ()

    def test_an_engine_has_nothing_to_prepare_by_default(self):
        engine = self.Plain()
        assert engine.pending(FakeCorpus(["a"])) == 0
        assert engine.sync(FakeCorpus(["a"])) == SyncReport()

    def test_fake_credits_charge_and_run_out(self, tmp_path):
        host = FakeHost(tmp_path / "v.db")
        host.credits = FakeCredits(1000, {"semantic": 0.25})
        assert host.credits.rate("semantic", 0.5) == 0.25 and host.credits.rate("x", 2.0) == 2.0
        host.credits.charge(400, note="page")
        assert host.credits.balance_milli() == 600 and host.credits.charges == [(400, "page")]
        with pytest.raises(CreditsExhaustedError):
            host.credits.charge(601)
        assert host.credits.balance_milli() == 600

    def test_the_host_has_a_folder_of_its_own(self, tmp_path):
        folder = FakeHost(tmp_path / "v.db").data_dir()
        assert folder.is_dir() and folder.parent == tmp_path
