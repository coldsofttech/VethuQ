import pytest
from search_data import SearchData
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.like import LikeSearchEngine
from vethuq_core.settings import InvalidSettingValueError, SearchSettings, Settings


class TestNormalizeSettings:
    def test_everything_defaults_to_auto(self, storage):
        assert SearchSettings.get_case(storage) == "auto"
        assert SearchSettings.get_leetspeak(storage) == "auto"
        assert SearchSettings.is_case_sensitive(storage) is False

    def test_set_and_get_case(self, storage):
        SearchSettings.set_case(storage, " Match ")

        assert SearchSettings.get_case(storage) == "match"
        assert SearchSettings.is_case_sensitive(storage) is True
        SearchSettings.set_case(storage, "auto")
        assert SearchSettings.is_case_sensitive(storage) is False

    def test_the_old_on_off_case_setting_still_works_both_ways(self, storage):
        SearchSettings.set_case_sensitive(storage, True)
        assert SearchSettings.get_case(storage) == "match"
        SearchSettings.set_case_sensitive(storage, False)
        assert SearchSettings.get_case(storage) == "ignore"

    def test_a_database_with_only_the_old_case_setting_reads_it(self, storage):
        Settings.set(storage, SearchSettings.CASE_SENSITIVE_KEY, "true")
        assert SearchSettings.get_case(storage) == "match"
        Settings.set(storage, SearchSettings.CASE_SENSITIVE_KEY, "false")
        assert SearchSettings.get_case(storage) == "ignore"
        SearchSettings.set_case(storage, "auto")  # the new key wins
        assert SearchSettings.get_case(storage) == "auto"

    def test_set_and_get_leetspeak(self, storage):
        for value in ("off", "Basic", "standard", "extended", "auto"):
            SearchSettings.set_leetspeak(storage, value)
            assert SearchSettings.get_leetspeak(storage) == value.lower()

    def test_a_database_with_only_the_old_leetspeak_level_reads_it(self, storage):
        Settings.set(storage, SearchSettings.LEGACY_LEETSPEAK_KEY, "extended")

        assert SearchSettings.get_leetspeak(storage) == "extended"

    def test_rejects_unknown_values(self, storage):
        with pytest.raises(InvalidSettingValueError, match="ignore, match"):
            SearchSettings.set_case(storage, "sometimes")
        with pytest.raises(InvalidSettingValueError, match="off, basic, standard, extended"):
            SearchSettings.set_leetspeak(storage, "insane")
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.parse_case("auto")  # `auto` is only for the stored setting
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.parse_leetspeak("auto")
        assert SearchSettings.get_case(storage) == "auto"

    def test_corrupt_stored_values_read_as_auto(self, storage):
        Settings.set(storage, SearchSettings.NORMALIZE_CASE_KEY, "bogus")
        Settings.set(storage, SearchSettings.NORMALIZE_LEETSPEAK_KEY, "bogus")

        assert SearchSettings.get_case(storage) == "auto"
        assert SearchSettings.get_leetspeak(storage) == "auto"

    def test_resolve_leetspeak_uses_the_engines_default_on_auto(self, storage):
        assert SearchSettings.resolve_leetspeak(storage, "off") == "off"
        assert SearchSettings.resolve_leetspeak(storage, "basic") == "basic"
        SearchSettings.set_leetspeak(storage, "standard")
        assert SearchSettings.resolve_leetspeak(storage, "off") == "standard"
        SearchSettings.set_leetspeak(storage, "off")
        assert SearchSettings.resolve_leetspeak(storage, "basic") == "off"

    def test_leetspeak_is_not_an_engine_any_more(self):
        assert "leetspeak" not in SearchSettings.ENGINES


def _found(storage, query, **kwargs):
    return [m.matched for m in Search.indexed_content(storage, query, engine="like", **kwargs)]


class TestLikeLookalikes:
    @pytest.mark.parametrize(
        ("query", "text", "found"),
        [
            ("hello", "say h3ll0 to all", ["h3ll0"]),
            ("password", "the p@55w0rd is", ["p@55w0rd"]),
            ("h3ll0", "say hello to all", ["hello"]),
            ("p@55w0rd", "the password is", ["password"]),
            ("hello", "say hello to all", ["hello"]),
            ("hello", "say HeLLo to all", ["HeLLo"]),
            ("hello", "say he11o to all", ["he11o"]),  # 1 is l
            ("hello", "say h3ll0!! to all", ["h3ll0"]),
            ("hello", "say h4ll0 to all", []),  # 4 is a
            ("hello", "say hallo to all", []),  # no typo tolerance
            ("hell", "say h3ll0 to all", ["h3ll"]),  # still a substring match, not whole words
        ],
    )
    def test_basic(self, conn, storage, query, text, found):
        SearchData.seed_page(conn, text)

        assert _found(storage, query, level="basic") == found

    def test_off_by_default(self, conn, storage):
        SearchData.seed_page(conn, "say h3ll0 to all")

        assert _found(storage, "hello") == []
        assert _found(storage, "hello", level="off") == []

    def test_the_stored_setting_turns_it_on(self, conn, storage):
        SearchData.seed_page(conn, "say h3ll0 to all")

        SearchSettings.set_leetspeak(storage, "basic")

        assert _found(storage, "hello") == ["h3ll0"]
        assert _found(storage, "hello", level="off") == []  # a per-search value wins

    def test_both_spellings_match_each_other(self, conn, storage):
        SearchData.seed_page(conn, "hello and h3ll0 and H3LL0")

        assert _found(storage, "hello", level="basic") == ["hello", "h3ll0", "H3LL0"]
        assert _found(storage, "h3ll0", level="basic") == ["hello", "h3ll0", "H3LL0"]

    def test_phrases_keep_their_spacing(self, conn, storage):
        SearchData.seed_page(conn, "my p@55w0rd is s3cr3t")

        assert _found(storage, "my password is secret", level="basic") == ["my p@55w0rd is s3cr3t"]
        assert _found(storage, "password secret", level="basic") == []

    def test_ambiguous_characters_match_each_of_their_letters(self, conn, storage):
        SearchData.seed_page(conn, "w1ld and 1ive and a1l")

        assert _found(storage, "wild", level="basic") == ["w1ld"]
        assert _found(storage, "live", level="basic") == ["1ive"]
        assert _found(storage, "all", level="basic") == ["a1l"]

    def test_case(self, conn, storage):
        SearchData.seed_page(conn, "Hello H3ll0 hello")

        assert _found(storage, "hello", level="basic") == ["Hello", "H3ll0", "hello"]
        assert _found(storage, "hello", level="basic", case_sensitive=True) == ["hello"]
        assert _found(storage, "Hello", level="basic", case_sensitive=True) == ["Hello", "H3ll0"]

    def test_levels_add_look_alikes(self, conn, storage):
        SearchData.seed_page(conn, "b@+ and 9ame and 2oo and w!n")

        for query in ("bat", "game", "zoo", "win"):
            assert _found(storage, query, level="basic") == []
        assert _found(storage, "bat", level="standard") == ["b@+"]
        assert _found(storage, "game", level="standard") == ["9ame"]
        assert _found(storage, "zoo", level="standard") == ["2oo"]
        assert _found(storage, "win", level="standard") == ["w!n"]
        assert _found(storage, "clock", level="standard") == []

    def test_extended_reads_brackets_as_c(self, conn, storage):
        SearchData.seed_page(conn, "a [lock on it")

        assert _found(storage, "clock", level="standard") == []
        assert _found(storage, "clock", level="extended") == ["[lock"]

    def test_scores_the_share_matched_as_typed(self, conn, storage):
        SearchData.seed_page(conn, "p@55w0rd", path="/docs/b_disguised.pdf")
        SearchData.seed_page(conn, "password", path="/docs/z_plain.pdf")

        matches = Search.indexed_content(storage, "password", engine="like", level="basic")

        assert {m.file_name: m.score for m in matches} == {
            "b_disguised.pdf": pytest.approx(4 / 8),  # p, w, r and d as typed
            "z_plain.pdf": 1.0,
        }

    def test_without_look_alikes_there_is_no_score(self, conn, storage):
        SearchData.seed_page(conn, "say hello")

        (match,) = Search.indexed_content(storage, "hello", engine="like")

        assert match.score is None

    def test_reports_where_the_match_is_and_its_context(self, conn, storage):
        SearchData.seed_page(conn, "log in with a p@55w0rd today")

        (match,) = Search.indexed_content(
            storage, "password", engine="like", level="basic", context_chars=5
        )

        assert (match.before, match.matched, match.after) == ("th a ", "p@55w0rd", " toda")
        assert (match.start, match.end) == (14, 22)
        assert match.engine == "like"

    def test_searches_image_pages_and_text_across_lines(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/scan.png", "image")
        SearchData.add_image_page(conn, document_id, "my\np@55w0rd")

        assert _found(storage, "my password", level="basic") == ["my p@55w0rd"]

    def test_query_symbols_are_literal_not_regex(self, conn, storage):
        SearchData.seed_page(conn, "a (test) [x] b.c")

        assert _found(storage, "(test)", level="basic") == ["(test)"]
        assert _found(storage, "b.c", level="basic") == ["b.c"]
        assert _found(storage, "b?c", level="basic") == []

    def test_short_or_letterless_queries_are_searched_as_they_are(self, conn, storage):
        SearchData.seed_page(conn, "it is 2024 and 1990 and 007 and 4 sale")

        assert _found(storage, "it", level="basic") == ["it"]
        assert _found(storage, "2024", level="basic") == ["2024"]  # not "zoza" or "ZOZA"
        assert _found(storage, "007", level="basic") == ["007"]
        assert LikeSearchEngine.has_lookalikes("hello") and LikeSearchEngine.has_lookalikes("a b c")
        assert not LikeSearchEngine.has_lookalikes("it")
        assert not LikeSearchEngine.has_lookalikes("2024")
        assert not LikeSearchEngine.has_lookalikes("  ")

    def test_an_unknown_level_is_rejected(self, storage):
        with pytest.raises(InvalidSettingValueError):
            Search.indexed_content(storage, "hello", engine="like", level="insane")

    def test_skips_documents_that_are_not_indexed(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/x.pdf", status="error")
        SearchData.add_pdf_page(conn, document_id, 1, "h3ll0")

        assert _found(storage, "hello", level="basic") == []

    def test_pages_without_a_recorded_skeleton_are_still_searched(self, conn, storage):
        SearchData.seed_page(conn, "say h3ll0 to all")
        conn.execute("UPDATE pdf_pages SET noise_text = ''")
        conn.commit()

        assert _found(storage, "hello", level="basic") == ["h3ll0"]

    @pytest.mark.parametrize("query", ["hello", "password", "h3ll0", "wor1d", "my password"])
    def test_narrowing_never_loses_a_match(self, conn, storage, monkeypatch, query):
        pages = [
            "say h3ll0 to all",
            "nothing here",
            "the p@55w0rd is",
            "HELLO",
            "he11o there",
            "my p@ssw0rd",
            "w0r1d",
        ]
        for number, text in enumerate(pages):
            SearchData.seed_page(conn, text, path=f"/docs/{number}.pdf")
        narrowed = [
            m.matched for m in Search.indexed_content(storage, query, engine="like", level="basic")
        ]

        monkeypatch.setattr(SearchEngineHelpers, "trigram_match", staticmethod(lambda _: None))
        everything = [
            m.matched for m in Search.indexed_content(storage, query, engine="like", level="basic")
        ]

        assert narrowed == everything and everything

    def test_other_engines_still_reject_a_level(self, storage):
        for engine in ("lexical", "exact", "full-text", "fuzzy", "proximity"):
            with pytest.raises(ValueError, match="leetspeak level"):
                Search.indexed_content(storage, "museum", engine=engine, level="basic")


class TestLookalikeOptions:
    def test_like_resolves_its_level_from_the_setting_or_off(self, storage):
        assert Search.resolve_options(storage, "like", None).level == "off"
        SearchSettings.set_leetspeak(storage, "standard")
        assert Search.resolve_options(storage, "like", None).level == "standard"
        assert Search.resolve_options(storage, "like", None, level="off").level == "off"
        assert Search.resolve_options(storage, "like", None, level="Extended").level == "extended"

    def test_the_combined_search_defaults_to_basic_unless_told_otherwise(self, storage):
        assert Search.resolve_options(storage, None, None).level == "basic"
        SearchSettings.set_leetspeak(storage, "off")
        assert Search.resolve_options(storage, None, None).level == "off"
        assert Search.resolve_options(storage, None, None, level="extended").level == "extended"

    def test_other_engines_take_no_level(self, storage):
        for engine in ("lexical", "exact", "full-text", "fuzzy", "proximity"):
            with pytest.raises(SearchOptionError) as error:
                Search.resolve_options(storage, engine, None, level="basic")
            assert error.value.option == "level"
            assert "Only the like and noise-fuzzy engines" in str(error.value)
            assert Search.resolve_options(storage, engine, None).level is None

    def test_an_invalid_level_names_the_values(self, storage):
        with pytest.raises(SearchOptionError, match="off, basic, standard, extended") as error:
            Search.resolve_options(storage, "like", None, level="insane")
        assert error.value.option == "level"

    def test_a_leetspeak_engine_is_an_unknown_engine(self, storage):
        with pytest.raises(SearchOptionError) as error:
            Search.resolve_options(storage, "leetspeak", None)
        assert error.value.option == "engine"
