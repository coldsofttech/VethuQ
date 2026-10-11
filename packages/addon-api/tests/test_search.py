from __future__ import annotations

import pytest

from vethuq_addon_api import (
    API_VERSION,
    Addon,
    Folded,
    Hit,
    Manifest,
    NormalizerUse,
    PageText,
    Pipeline,
    SearchEngine,
    SearchEngineSpec,
    SearchQueryError,
    SearchRequest,
)
from vethuq_addon_api.testing import FakeCorpus, FakeHost, FakeNormalizer


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

    def test_the_api_version(self):
        assert API_VERSION == "0.5.0"
