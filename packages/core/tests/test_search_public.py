from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq.enums import SearchSortBy, SortOrder
from vethuq.search import (
    NormalizerInfo,
    Search,
    SearchEngineInfo,
    SearchIndexStatus,
    SearchMatch,
    SearchResult,
)
from vethuq_addon_api.testing import FakeNormalizer

CAFE = "café"
CAFE_DECOMPOSED = "café"


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


def native(text_):
    return fp.native_page(text_)


@pytest.fixture
def indexed(client, root):
    write(
        root, "museum.pdf", native("Visit the Museum today. Museums are open."), native("Nothing")
    )
    write(root, "cafe.pdf", native(f"A {CAFE} near the CAFE sign, naive {CAFE_DECOMPOSED}"))
    write(root, "invoice.pdf", native("Invoice 2024-001 total $1,200.00 due.\nSecond line here"))
    client.sources.create(root)
    assert client.index.run().status.value == "completed"
    return client


def found(result):
    return [(m.file_name, m.page_number, m.matched) for m in result]


class TestEnginesAndNormalizers:
    def test_the_installed_engines(self, client):
        engines = client.search.engines()
        installed = [e.id for e in engines]
        assert installed[:2] == ["exact", "like"]  # strictest first
        assert {"lexical", "proximity", "full-text", "fuzzy", "noise-fuzzy"} <= set(installed)
        assert (
            installed.index("proximity") < installed.index("full-text") < installed.index("fuzzy")
        )
        like = next(e for e in engines if e.id == "like")
        assert isinstance(like, SearchEngineInfo)
        assert (
            like.available
            and like.in_all
            and like.normalizers
            == {
                "unicode": "basic",
                "case": "ignore",
                "leetspeak": "off",  # an optional normalizer, there because its add-on is installed
            }
        )
        fuzzy = next(e for e in engines if e.id == "fuzzy")
        assert fuzzy.approximate and fuzzy.options == {"threshold": "balanced"}
        assert not like.approximate and like.options == {}
        assert not like.selected  # the default is `all`
        assert json.loads(like.to_json()) == like.to_dict()

    def test_the_installed_normalizers_in_the_order_they_apply(self, client):
        normalizers = client.search.normalizers()
        assert [n.id for n in normalizers] == ["unicode", "case", "leetspeak"]
        case = normalizers[1]
        assert isinstance(case, NormalizerInfo)
        assert (case.levels, case.identity, case.setting) == (("match", "ignore"), "match", "auto")

    def test_the_default_engine_is_marked(self, client):
        client.settings.search.set_engine("like")
        assert {e.id for e in client.search.engines() if e.selected} == {"like"}


class TestRunning:
    def test_like_finds_a_substring_ignoring_case(self, indexed):
        result = indexed.search.run("MUS", engine="like")
        assert isinstance(result, SearchResult) and isinstance(result[0], SearchMatch)
        assert found(result) == [
            ("museum.pdf", 1, "Mus"),
            ("museum.pdf", 1, "Mus"),
        ]
        assert result.engine == "like" and result.total == 2

    def test_a_match_carries_its_context(self, indexed):
        (match, *_) = indexed.search.run("today", engine="like", context_chars=5)
        assert (match.before, match.matched, match.after) == ("seum ", "today", ". Mus")
        assert match.truncated_before and match.truncated_after
        assert match.page_number == 1 and match.total_pages == 2 and match.source == "native"
        assert match.end - match.start == 5

    def test_the_whole_context_is_not_truncated(self, indexed):
        (match,) = indexed.search.run("Nothing", engine="like", context_chars=50)
        assert (match.before, match.after) == ("", "") and not match.truncated_before

    def test_exact_is_a_whole_word_in_the_case_typed(self, indexed):
        assert found(indexed.search.run("Museum", engine="exact")) == [("museum.pdf", 1, "Museum")]
        assert indexed.search.run("museum", engine="exact").matches == []
        assert indexed.search.run("Mus", engine="exact").matches == []

    def test_exact_with_a_symbol_query(self, indexed):
        assert found(indexed.search.run("$1,200.00", engine="exact")) == [
            ("invoice.pdf", 1, "$1,200.00")
        ]

    def test_line_breaks_are_spaces(self, indexed):
        (match,) = indexed.search.run("due. Second", engine="like")
        assert match.matched == "due. Second"

    def test_all_merges_what_engines_agree_on(self, indexed):
        result = indexed.search.run("Museum")
        first = next(m for m in result if (m.page_number, m.start, m.end) == (1, 10, 16))
        assert first.engine == "exact" and first.matched_by[:2] == ("exact", "like")
        assert first.matched_by[2:] == tuple(  # strictest first
            e for e in ("lexical", "full-text", "fuzzy", "noise-fuzzy") if e in first.matched_by
        )
        # "Museums": the exact engine doesn't find it, `like` does (and every engine that overlaps
        # it is merged into that match, whose span is the strictest engine's).
        inside = [m for m in result if m.matched == "Museum" and m.start > 16]
        assert inside and all(m.engine == "like" and "exact" not in m.matched_by for m in inside)
        assert result.engine == "all" and {"exact", "like"} <= set(result.levels)

    def test_the_levels_each_engine_ran_at_are_reported(self, indexed):
        result = indexed.search.run("x")
        assert result.levels["like"] == {"unicode": "basic", "case": "ignore", "leetspeak": "off"}
        assert result.levels["exact"] == {"unicode": "basic", "case": "match"}

    def test_an_empty_query_matches_nothing(self, indexed):
        assert indexed.search.run("").matches == [] and indexed.search.run("   ").total == 0

    def test_a_query_nothing_has(self, indexed):
        assert indexed.search.run("zzzzzz").matches == []

    def test_short_queries_are_searched_too(self, indexed):
        assert {m.file_name for m in indexed.search.run("No", engine="like")} == {"museum.pdf"}
        assert indexed.search.run("2", engine="like").total >= 1

    def test_the_query_must_be_text(self, indexed):
        with pytest.raises(TypeError):
            indexed.search.run(5)


class TestNormalization:
    def test_like_composes_unicode_by_default(self, indexed):
        result = indexed.search.run(CAFE, engine="like")
        assert sorted(m.matched for m in result) == sorted([CAFE, CAFE_DECOMPOSED])

    def test_accents_are_folded_only_when_asked(self, indexed):
        # Without composing, "cafe" is also the start of the decomposed "cafe" + accent.
        assert indexed.search.run("cafe", engine="like", normalize={"unicode": "off"}).total == 2
        plain = indexed.search.run("cafe", engine="like")
        assert [m.matched for m in plain] == ["CAFE"]  # the accented ones are different text
        full = indexed.search.run("cafe", engine="like", normalize={"unicode": "full"})
        assert {m.matched for m in full} == {CAFE, "CAFE", CAFE_DECOMPOSED}
        assert any("accents" in m.modifiers for m in full)
        assert not any("accents" in m.modifiers for m in full if m.matched == "CAFE")

    def test_the_highlight_is_the_original_text(self, indexed):
        full = indexed.search.run("naive", engine="like", normalize="unicode=full", context_chars=0)
        (match,) = full.matches
        assert match.matched == "naive" and match.modifiers == ()

    def test_case_sensitive_is_shorthand_for_the_case_level(self, indexed):
        assert indexed.search.run("mus", engine="like", case_sensitive=True).total == 0
        assert indexed.search.run("Mus", engine="like", case_sensitive=True).total == 2
        assert indexed.search.run("mus", engine="like", case_sensitive=False).total == 2
        assert indexed.search.run("mus", engine="like", normalize={"case": "match"}).total == 0

    def test_a_saved_level_applies_to_engines_that_take_it(self, indexed):
        indexed.settings.search.set_case("match")
        assert indexed.search.run("mus", engine="like").total == 0
        assert indexed.search.run("Mus", engine="like").total == 2
        indexed.settings.search.set_unicode("full")
        assert {m.matched for m in indexed.search.run("cafe", engine="like")} >= {CAFE}
        indexed.settings.search.reset_case()
        assert indexed.search.run("mus", engine="like").total == 2

    def test_exact_ignores_the_saved_unicode_level_but_honours_a_request(self, indexed):
        indexed.settings.search.set_unicode("full")
        assert indexed.search.run("cafe", engine="exact").total == 0
        asked = indexed.search.run("cafe", engine="exact", normalize={"unicode": "full"})
        assert sorted(m.matched for m in asked) == sorted([CAFE, CAFE_DECOMPOSED])  # not "CAFE"
        assert {
            m.matched for m in indexed.search.run("CAFE", engine="exact", normalize="unicode=full")
        } == {"CAFE"}

    def test_exact_cannot_be_made_case_insensitive(self, indexed):
        with pytest.raises(errors.SearchOptionError) as caught:
            indexed.search.run("museum", engine="exact", case_sensitive=False)
        assert caught.value.option == "case"
        with pytest.raises(errors.SearchOptionError):
            indexed.search.run("museum", engine="exact", normalize={"case": "ignore"})

    def test_in_the_all_search_exact_simply_stays_exact(self, indexed):
        result = indexed.search.run("museum", case_sensitive=False)
        assert {m.engine for m in result} == {"like"} and result.levels["exact"]["case"] == "match"

    def test_bad_options(self, indexed):
        for kwargs in (
            {"normalize": {"nope": "x"}},
            {"normalize": {"case": "sideways"}},
            {"normalize": "case"},
            {"normalize": "case=match,case=ignore"},
            {"case_sensitive": True, "normalize": {"case": "ignore"}},
        ):
            with pytest.raises(errors.SearchOptionError):
                indexed.search.run("x", **kwargs)

    def test_an_engine_that_does_not_use_a_normalizer_refuses_it(self, indexed, monkeypatch):
        extra = FakeNormalizer("extra")
        engines = indexed._search_catalog()
        original = engines._normalizers
        monkeypatch.setattr(engines, "_normalizers", lambda: [*original(), extra])
        with pytest.raises(errors.SearchOptionError, match="doesn't use"):
            indexed.search.run("x", engine="like", normalize={"extra": "on"})
        with pytest.raises(errors.SearchOptionError, match="No search engine uses"):
            indexed.search.run("x", normalize={"extra": "on"})


class TestEnginesChoice:
    def test_an_unknown_engine(self, indexed):
        with pytest.raises(errors.SearchUnavailableError, match="no search engine 'nope'"):
            indexed.search.run("x", engine="nope")

    def test_a_saved_default_engine_is_used(self, indexed):
        indexed.settings.search.set_engine("exact")
        assert indexed.search.run("Mus").total == 0
        assert indexed.search.run("Mus").engine == "exact"
        indexed.settings.search.reset_engine()
        assert indexed.search.run("Mus").engine == "all"

    def test_an_engine_whose_normalizer_is_missing_is_unavailable(self, indexed, monkeypatch):
        engines = indexed._search_catalog()
        original = engines._normalizers
        monkeypatch.setattr(
            engines, "_normalizers", lambda: [n for n in original() if n.id != "case"]
        )
        listed = {e.id: e for e in indexed.search.engines()}
        assert not listed["like"].available and "needs the case normalizer" in listed["like"].reason
        with pytest.raises(errors.SearchUnavailableError, match="can't be used"):
            indexed.search.run("x", engine="like")

    def test_no_engines_at_all(self, indexed, monkeypatch):
        monkeypatch.setattr(indexed._search_catalog(), "_specs", lambda: [])
        with pytest.raises(errors.SearchUnavailableError, match="No search engine"):
            indexed.search.run("x")

    def test_a_failing_engine_does_not_spoil_the_all_search(self, indexed, monkeypatch):
        spec = indexed._search_catalog()._specs()[0]  # exact

        class Broken:
            def search(self, request, corpus):
                raise RuntimeError("boom")

        broken = type(spec)(spec.id, spec.label, Broken(), spec.normalizers, strictness=1)
        others = [s for s in indexed._search_catalog()._specs() if s.id != spec.id]
        monkeypatch.setattr(indexed._search_catalog(), "_specs", lambda: [broken, *others])
        assert indexed.search.run("Museum").total > 0
        with pytest.raises(RuntimeError):
            indexed.search.run("Museum", engine=spec.id)

    def test_a_query_an_engine_cannot_search(self, indexed, monkeypatch):
        from vethuq_addon_api import SearchQueryError

        spec = indexed._search_catalog()._specs()[1]

        class Picky:
            def search(self, request, corpus):
                raise SearchQueryError("needs two words")
                yield

        picky = type(spec)("picky", "Picky", Picky(), spec.normalizers)
        monkeypatch.setattr(indexed._search_catalog(), "_specs", lambda: [picky])
        with pytest.raises(errors.SearchQueryError, match="two words"):
            indexed.search.run("x", engine="picky")


class TestResults:
    def test_sorting_and_paging(self, indexed):
        everything = indexed.search.run("e", engine="like")
        paths = [(m.file_path, m.page_number, m.start) for m in everything]
        assert paths == sorted(paths) and everything.total == len(everything.matches)
        page = indexed.search.run("e", engine="like", limit=3, offset=2)
        assert [m.start for m in page] == [m.start for m in everything.matches[2:5]]
        assert page.total == everything.total and len(page) == 3
        backwards = indexed.search.run("e", engine="like", order=SortOrder.DESC)
        assert [m.start for m in backwards] == [m.start for m in reversed(everything.matches)]

    def test_sorting_by_score_puts_unscored_last(self, indexed):
        result = indexed.search.run("Museum", engine="like", sort=SearchSortBy.SCORE)
        assert result.total > 0 and all(m.score is None for m in result)
        mixed = indexed.search.run("Museum", sort=SearchSortBy.SCORE)
        scores = [m.score for m in mixed]
        assert any(score is not None for score in scores)
        scored = [score for score in scores if score is not None]
        assert scores[: len(scored)] == sorted(scored, reverse=True)  # scored first, best first
        assert all(score is None for score in scores[len(scored) :])

    def test_bad_paging_and_sorting(self, indexed):
        for kwargs in (
            {"limit": -1},
            {"offset": -1},
            {"limit": True},
            {"sort": "size"},
            {"order": "up"},
        ):
            with pytest.raises(ValueError):
                indexed.search.run("x", **kwargs)

    def test_results_have_json(self, indexed):
        result = indexed.search.run("Museum", limit=1)
        data = json.loads(result.to_json())
        assert data["total"] == result.total and data["matches"][0]["file_name"] == "museum.pdf"
        assert json.loads(result.matches[0].to_json()) == result.matches[0].to_dict()

    def test_duplicates_are_their_own_results(self, client, root):
        write(root, "a.pdf", native("shared words appear here"))
        write(root, "b.pdf", native("shared words appear here"))
        client.sources.create(root)
        client.index.run()
        result = client.search.run("shared", engine="like")
        assert [(m.file_name, m.duplicate_of_path) for m in result] == [
            ("a.pdf", None),
            ("b.pdf", str(root / "a.pdf")),
        ]

    def test_only_indexed_files_are_searched(self, indexed, root):
        (root / "museum.pdf").unlink()
        indexed.index.run()  # the file is gone: it is no longer `indexed`
        assert indexed.search.run("Museum", engine="like").total == 0

    def test_a_file_that_is_not_done_is_not_searched(self, indexed):
        with indexed._db().session() as session:
            session.execute(
                text("UPDATE pdf_pages SET status = 'waiting' WHERE text LIKE '%Invoice%'")
            )
        assert indexed.search.run("Invoice", engine="like").total == 0

    def test_languages_keep_pages_of_documents_read_in_them(self, indexed):
        assert indexed.search.run("Museum", engine="like", languages="en").total > 0
        assert indexed.search.run("Museum", engine="like", languages=["en"]).total > 0
        assert indexed.search.run("Museum", engine="like", languages="te").total == 0
        assert indexed.search.run("Museum", engine="like", languages=[]).total == 0


class TestIndex:
    def test_a_run_brings_the_index_up_to_date(self, indexed):
        status = indexed.search.status()
        assert isinstance(status, SearchIndexStatus)
        assert status.pages_indexed == status.pages_total == 4 and status.current
        assert status.full_text and json.loads(status.to_json())["pages_total"] == 4

    def test_the_index_holds_the_coarse_form(self, indexed):
        with indexed._db().session() as session:
            forms = {r[0] for r in session.execute(text("SELECT norm_text FROM page_search")).all()}
        assert any("cafe" in form and "CAFE" not in form for form in forms)  # folded and lowered

    def test_changed_text_loses_its_row_until_the_next_sync(self, indexed):
        with indexed._db().session() as session:
            session.execute(text("UPDATE pdf_pages SET text = 'brand new words' WHERE id = 1"))
        assert indexed.search.status().pages_indexed == 3
        assert indexed.search.run("brand new", engine="like").total == 1  # the search syncs first
        assert indexed.search.status().pages_indexed == 4

    def test_deleted_pages_leave_the_index(self, indexed):
        with indexed._db().session() as session:
            session.execute(text("DELETE FROM documents"))
        assert indexed.search.status().pages_indexed == 0
        with indexed._db().session() as session:
            assert session.execute(text("SELECT count(*) FROM page_search_fts")).scalar_one() == 0

    def test_new_normalizers_rebuild_the_index_once(self, indexed, monkeypatch):
        extra = FakeNormalizer("extra", {"x": "y"}, order=5)
        engines = indexed._search_catalog()
        original = engines._normalizers
        monkeypatch.setattr(indexed._search_indexer(), "_normalizers", lambda: [*original(), extra])
        assert not indexed.search.status().current
        first = indexed.search.run("Museum", engine="like")
        assert first.index_rebuilt and first.total > 0
        assert indexed.search.status().current
        assert not indexed.search.run("Museum", engine="like").index_rebuilt

    def test_the_first_build_is_not_a_rebuild(self, client, root):
        write(root, "a.pdf", native("some words"))
        client.sources.create(root)
        client.index.run()
        assert not client.search.run("some", engine="like").index_rebuilt

    def test_rebuild_builds_it_again(self, indexed):
        result = indexed.search.rebuild()
        assert result.ok and result.pages == 4 and result.seconds >= 0
        assert indexed.search.status().pages_indexed == 4

    def test_without_the_trigram_index_searches_still_work(self, indexed, monkeypatch):
        monkeypatch.setattr(indexed._search_indexer(), "has_fts", lambda: False)
        assert indexed.search.run("Museum", engine="like").total > 0
        assert indexed.search.run("ab", engine="like").total == 0

    def test_short_queries_scan_the_index(self, indexed):
        assert indexed.search.run("mu", engine="like").total >= 2

    def test_a_search_before_any_run_works(self, client):
        assert client.search.run("anything").total == 0
        assert client.search.status().pages_total == 0

    def test_pages_from_many_batches(self, client, root, monkeypatch):
        from vethuq._search import _SearchIndex

        monkeypatch.setattr(_SearchIndex, "BATCH", 2)
        write(root, "big.pdf", *[native(f"page number {i} has the word zebra") for i in range(7)])
        client.sources.create(root)
        client.index.run()
        assert client.search.run("zebra", engine="like").total == 7
        assert client.search.status().pages_indexed == 7


class TestSettings:
    def test_defaults(self, client):
        s = client.settings.search
        assert (s.get_engine(), s.get_snippet_context_chars(), s.get_case(), s.get_unicode()) == (
            "all",
            80,
            "auto",
            "auto",
        )

    def test_engine(self, client):
        s = client.settings.search
        s.set_engine("like")
        assert s.get_engine() == "like"
        with pytest.raises(errors.InvalidSettingValueError, match="isn't a search engine"):
            s.set_engine("nope")
        s.set_engine("all")
        s.reset_engine()
        assert s.get_engine() == "all"

    def test_snippet_context(self, client):
        s = client.settings.search
        s.set_snippet_context_chars(10)
        assert s.get_snippet_context_chars() == 10
        for bad in (-1, 2001, 1.5, "5", True):
            with pytest.raises(errors.InvalidSettingValueError):
                s.set_snippet_context_chars(bad)
        s.reset_snippet_context_chars()
        assert s.get_snippet_context_chars() == 80

    def test_a_saved_context_is_used(self, indexed):
        indexed.settings.search.set_snippet_context_chars(3)
        (match,) = indexed.search.run("Nothing", engine="like")
        assert (match.before, match.after) == ("", "")
        (match,) = indexed.search.run("today", engine="like")
        assert (match.before, match.after) == ("um ", ". M")

    def test_normalizers(self, client):
        s = client.settings.search
        s.set_normalizer("case", "match")
        assert s.get_normalizer("case") == "match" == s.get_case()
        s.set_unicode("full")
        assert s.get_unicode() == "full"
        s.set_normalizer("case", "auto")
        assert s.get_case() == "auto"
        s.reset_unicode()
        assert s.get_unicode() == "auto"
        for normalizer, level in (("nope", "x"), ("case", "sideways"), ("case", "")):
            with pytest.raises(errors.InvalidSettingValueError):
                s.set_normalizer(normalizer, level)

    def test_a_saved_level_that_no_longer_exists_falls_back(self, indexed):
        with indexed._db().session() as session:
            session.execute(
                text("INSERT INTO settings (key, value) VALUES ('search_normalize_case', 'gone')")
            )
        assert indexed.search.run("mus", engine="like").total == 2  # the engine's own level


class TestErrors:
    def test_exit_codes_and_hierarchy(self, indexed):
        for error in (
            errors.SearchError,
            errors.SearchUnavailableError,
            errors.SearchOptionError,
            errors.SearchQueryError,
        ):
            assert issubclass(error, errors.VethuQError)
        from vethuq._errors import _SearchOptionError, _SearchQueryError, _SearchUnavailableError

        assert (_SearchUnavailableError.exit_code, _SearchOptionError.exit_code) == (91, 92)
        assert _SearchQueryError.exit_code == 93

    def test_the_search_property_is_stable(self, client):
        assert isinstance(client.search, Search) and client.search is client.search


class TestScope:
    @pytest.fixture
    def two_sources(self, client, tmp_path):
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        write(first, "report.pdf", native("The harvest report mentions wheat."))
        (first / "notes.txt").write_text("Notes about wheat and barley.", encoding="utf-8")
        (second / "memo.txt").write_text("A memo on wheat prices.", encoding="utf-8")
        a = client.sources.create(first)
        b = client.sources.create(second)
        assert client.index.run().status.value == "completed"
        return client, a.id, b.id

    def test_a_match_says_what_kind_of_file_it_is(self, two_sources):
        client, *_ = two_sources
        kinds = {m.file_name: m.file_type for m in client.search.run("wheat", engine="like")}
        assert kinds == {"report.pdf": "pdf", "notes.txt": "txt", "memo.txt": "txt"}
        assert "file_type" in client.search.run("wheat", engine="like")[0].to_dict()

    def test_file_types_narrow_the_search_and_the_total(self, two_sources):
        client, *_ = two_sources
        only_pdf = client.search.run("wheat", engine="like", file_types="pdf")
        assert [m.file_name for m in only_pdf] == ["report.pdf"] and only_pdf.total == 1
        both = client.search.run("wheat", engine="like", file_types=["pdf", "TXT"])
        assert {m.file_name for m in both} == {"report.pdf", "notes.txt", "memo.txt"}
        assert client.search.run("wheat", engine="like", file_types=["csv"]).total == 0
        assert client.search.run("wheat", engine="like", file_types=[]).total == 0

    def test_sources_narrow_the_search(self, two_sources):
        client, a, b = two_sources
        assert {m.file_name for m in client.search.run("wheat", engine="like", sources=a)} == {
            "report.pdf",
            "notes.txt",
        }
        assert [m.file_name for m in client.search.run("wheat", engine="like", sources=[b])] == [
            "memo.txt"
        ]
        assert client.search.run("wheat", engine="like", sources=[999]).total == 0

    def test_both_filters_together_and_paging_counts_what_is_kept(self, two_sources):
        client, a, _ = two_sources
        result = client.search.run(
            "wheat", engine="like", file_types="txt", sources=a, limit=1, offset=0
        )
        assert [m.file_name for m in result] == ["notes.txt"] and result.total == 1

    def test_the_other_engines_respect_it_too(self, two_sources):
        client, *_ = two_sources
        for engine in ("exact", "full-text", "all"):
            result = client.search.run("wheat", engine=engine, file_types="pdf")
            assert {m.file_name for m in result} <= {"report.pdf"}, engine

    def test_a_duplicate_still_names_the_true_original(self, client, tmp_path):
        first, second = tmp_path / "x", tmp_path / "y"
        first.mkdir()
        second.mkdir()
        (first / "one.txt").write_text("identical words about barley", encoding="utf-8")
        (second / "two.txt").write_text("identical words about barley", encoding="utf-8")
        client.sources.create(first)
        other = client.sources.create(second)
        client.index.run()
        (match,) = client.search.run("barley", engine="like", sources=other.id)
        assert match.file_name == "two.txt" and match.duplicate_of_path.endswith("one.txt")

    def test_bad_values_are_refused(self, two_sources):
        client, *_ = two_sources
        with pytest.raises(TypeError):
            client.search.run("wheat", file_types=[1])
        with pytest.raises(TypeError):
            client.search.run("wheat", sources=["a"])


class TestLocation:
    @pytest.fixture
    def texts(self, client, tmp_path):
        folder = tmp_path / "t"
        folder.mkdir()
        (folder / "story.txt").write_text(
            "first line\nsecond line has wheat in it\n\nfourth: more wheat", encoding="utf-8"
        )
        (folder / "data.csv").write_text("name,crop\nfarm,wheat\nmill,barley\n", encoding="utf-8")
        write(folder, "report.pdf", native("The wheat harvest."))
        client.sources.create(folder)
        assert client.index.run().status.value == "completed"
        return client

    def test_a_text_match_has_its_line_and_column(self, texts):
        found = {(m.file_name, m.line, m.column) for m in texts.search.run("wheat", engine="like")}
        assert ("story.txt", 2, 17) in found and ("story.txt", 4, 14) in found
        assert ("data.csv", 2, 6) in found  # a CSV row; the column counts in "farm | wheat"

    def test_a_pdf_match_has_a_page_and_no_line(self, texts):
        (pdf,) = [
            m for m in texts.search.run("wheat", engine="like") if m.file_name == "report.pdf"
        ]
        assert (pdf.page_number, pdf.line, pdf.column) == (1, None, None)
        assert "line" in pdf.to_dict() and "column" in pdf.to_dict()

    def test_the_line_points_at_the_matched_text(self, texts):
        for match in texts.search.run("wheat", engine="like", file_types="txt"):
            lines = open(match.file_path, encoding="utf-8").read().split("\n")
            start = match.column - 1
            assert lines[match.line - 1][start : start + 5] == "wheat"


class TestPageText:
    @pytest.fixture
    def texts(self, client, tmp_path):
        folder = tmp_path / "t"
        folder.mkdir()
        (folder / "story.txt").write_text("first line\nsecond line has wheat", encoding="utf-8")
        client.sources.create(folder)
        assert client.index.run().status.value == "completed"
        return client

    def test_the_stored_text_is_what_a_match_counts_in(self, texts):
        (match,) = texts.search.run("wheat", engine="like")
        page = texts.search.page_text(match.document_id, match.page_number)
        assert (page.file_name, page.file_type) == ("story.txt", "txt")
        assert page.text == "first line\nsecond line has wheat"
        assert page.text.split("\n")[match.line - 1][match.column - 1 :].startswith("wheat")

    def test_a_page_that_is_not_there_is_none(self, texts):
        (match,) = texts.search.run("wheat", engine="like")
        assert texts.search.page_text(match.document_id, 99) is None
        assert texts.search.page_text(987654) is None
