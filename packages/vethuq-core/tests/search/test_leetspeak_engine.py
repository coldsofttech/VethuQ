import re

import pytest
from search_data import SearchData
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines import SearchQueryError
from vethuq_core.search.engines.leetspeak import LeetspeakSearchEngine
from vethuq_core.settings import InvalidSettingValueError, SearchSettings, Settings


class TestLeetspeakSettings:
    def test_defaults_to_basic(self, storage):
        assert SearchSettings.get_leetspeak_level(storage) == "basic"
        assert SearchSettings.LEETSPEAK_LEVELS == ("basic", "standard", "extended")

    def test_set_and_get_level(self, storage):
        SearchSettings.set_leetspeak_level(storage, " Extended ")

        assert SearchSettings.get_leetspeak_level(storage) == "extended"

    def test_rejects_an_unknown_level(self, storage):
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.set_leetspeak_level(storage, "insane")

        assert SearchSettings.get_leetspeak_level(storage) == "basic"

    def test_a_corrupt_stored_level_falls_back_to_the_default(self, storage):
        Settings.set(storage, SearchSettings.LEETSPEAK_LEVEL_KEY, "bogus")

        assert SearchSettings.get_leetspeak_level(storage) == "basic"

    def test_is_a_known_engine(self):
        assert "leetspeak" in SearchSettings.ENGINES


class TestLeetspeakEngine:
    @staticmethod
    def _found(storage, query, **kwargs):
        return [
            m.matched for m in Search.indexed_content(storage, query, engine="leetspeak", **kwargs)
        ]

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
            ("hello", "say h3ll0!! to all", ["h3ll0"]),  # punctuation is not part of the word
            ("h3ll0", "say h3ll0 to all", ["h3ll0"]),
            ("hello", "say h4ll0 to all", []),  # 4 is a, not e
            ("hello", "say hallo to all", []),  # no typo tolerance - that's fuzzy
            ("hello", "say hello1 to all", []),  # a longer word
            ("hello", "say 5hello to all", []),
            ("hello", "shellout", []),  # whole words only
        ],
    )
    def test_basic_level(self, conn, storage, query, text, found):
        SearchData.seed_page(conn, text)

        assert self._found(storage, query) == found

    def test_the_two_spellings_of_one_word_both_match_each_other(self, conn, storage):
        SearchData.seed_page(conn, "hello and h3ll0 and H3LL0")

        assert self._found(storage, "hello") == ["hello", "h3ll0", "H3LL0"]
        assert self._found(storage, "h3ll0") == ["hello", "h3ll0", "H3LL0"]

    def test_phrases_match_word_by_word(self, conn, storage):
        SearchData.seed_page(conn, "my p@55w0rd   is  s3cr3t")

        assert self._found(storage, "my password is secret") == ["my p@55w0rd   is  s3cr3t"]
        assert self._found(storage, "password secret") == []  # not adjacent

    def test_ambiguous_characters_match_each_of_their_letters(self, conn, storage):
        SearchData.seed_page(conn, "w1ld and 1ive and a1l")

        assert self._found(storage, "wild") == ["w1ld"]
        assert self._found(storage, "live") == ["1ive"]
        assert self._found(storage, "all") == ["a1l"]

    def test_case_insensitive_unless_asked(self, conn, storage):
        SearchData.seed_page(conn, "Hello H3ll0 hello")

        assert self._found(storage, "hello") == ["Hello", "H3ll0", "hello"]
        assert self._found(storage, "hello", case_sensitive=True) == ["hello"]
        assert self._found(storage, "Hello", case_sensitive=True) == ["Hello", "H3ll0"]

    def test_standard_adds_more_substitutions(self, conn, storage):
        SearchData.seed_page(conn, "b@+ and 9ame and 2oo")

        assert self._found(storage, "bat") == []
        assert self._found(storage, "game") == []
        assert self._found(storage, "zoo") == []

        SearchSettings.set_leetspeak_level(storage, "standard")

        assert self._found(storage, "bat") == ["b@+"]
        assert self._found(storage, "game") == ["9ame"]
        assert self._found(storage, "zoo") == ["2oo"]

    def test_standard_punctuation_look_alikes(self, conn, storage):
        SearchData.seed_page(conn, "w!n and p|ay")

        assert self._found(storage, "win") == []
        SearchSettings.set_leetspeak_level(storage, "standard")
        assert self._found(storage, "win") == ["w!n"]
        assert self._found(storage, "play") == ["p|ay"]

    def test_extended_multi_character_look_alikes(self, conn, storage):
        SearchData.seed_page(conn, r"a |\|ice day and ph0ne and \/\/in")

        assert self._found(storage, "nice") == []
        SearchSettings.set_leetspeak_level(storage, "extended")
        assert self._found(storage, "nice") == [r"|\|ice"]
        assert self._found(storage, "phone") == ["ph0ne"]
        assert self._found(storage, "fone") == ["ph0ne"]
        assert self._found(storage, "win") == [r"\/\/in"]
        assert self._found(storage, r"|\|ice") == [r"|\|ice"]
        assert self._found(storage, "nice", case_sensitive=True) == [r"|\|ice"]

    def test_scores_the_share_matched_as_typed(self, conn, storage):
        SearchData.seed_page(conn, "p@55w0rd", path="/docs/b_disguised.pdf")
        SearchData.seed_page(conn, "password", path="/docs/z_plain.pdf")

        matches = Search.indexed_content(storage, "password", engine="leetspeak")

        assert [m.file_name for m in matches] == ["z_plain.pdf", "b_disguised.pdf"]
        assert matches[0].score == 1.0
        assert matches[1].score == pytest.approx(4 / 8)  # p, w, r and d as typed
        assert {m.engine for m in matches} == {"leetspeak"}

    def test_a_leet_query_scores_its_own_spelling_highest(self, conn, storage):
        SearchData.seed_page(conn, "h3ll0", path="/docs/b_same.pdf")
        SearchData.seed_page(conn, "hello", path="/docs/a_plain.pdf")

        matches = Search.indexed_content(storage, "h3ll0", engine="leetspeak")

        assert [m.file_name for m in matches] == ["b_same.pdf", "a_plain.pdf"]
        assert matches[0].score == 1.0
        assert matches[1].score == pytest.approx(3 / 5)  # the 3 and the 0 were substituted

    def test_reports_where_the_match_is_and_its_context(self, conn, storage):
        SearchData.seed_page(conn, "log in with a p@55w0rd today")

        (match,) = Search.indexed_content(storage, "password", engine="leetspeak", context_chars=5)

        assert (match.before, match.matched, match.after) == ("th a ", "p@55w0rd", " toda")
        assert (match.start, match.end) == (14, 22)
        assert match.truncated_before and match.truncated_after

    def test_searches_image_pages(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/scan.png", "image")
        SearchData.add_image_page(conn, document_id, "h3ll0 world")

        assert self._found(storage, "hello") == ["h3ll0"]

    def test_text_across_a_line_break_is_still_adjacent(self, conn, storage):
        SearchData.seed_page(conn, "my\np@55w0rd")

        assert self._found(storage, "my password") == ["my p@55w0rd"]

    def test_query_symbols_are_literal_not_regex(self, conn, storage):
        SearchData.seed_page(conn, "a (test) [x] b.c")

        assert self._found(storage, "(test)") == ["(test)"]
        assert self._found(storage, "b.c") == ["b.c"]
        assert self._found(storage, "b?c") == []
        assert self._found(storage, '"te"st') == []

    def test_needs_three_characters_and_a_letter(self, conn, storage):
        SearchData.seed_page(conn, "it is 2024 and 1990 and 007")

        with pytest.raises(SearchQueryError):
            self._found(storage, "it")
        with pytest.raises(SearchQueryError):
            self._found(storage, " a b ")
        assert self._found(storage, "2024") == []  # nothing to substitute: use like
        assert self._found(storage, "007") == []
        assert self._found(storage, "") == []
        assert self._found(storage, "   ") == []

    def test_rejects_a_threshold_or_distance(self, storage):
        with pytest.raises(ValueError, match="threshold"):
            Search.indexed_content(storage, "hello", engine="leetspeak", threshold=0.8)
        with pytest.raises(ValueError, match="distance"):
            Search.indexed_content(storage, "hello", engine="leetspeak", distance=3)

    def test_unicode_text_passes_through(self, conn, storage):
        SearchData.seed_page(conn, "Café and cafe and c@fé")

        assert self._found(storage, "café") == ["Café", "c@fé"]

    def test_level_can_be_given_to_the_engine_directly(self, conn, storage):
        SearchData.seed_page(conn, r"a |\|ice day")

        engine = LeetspeakSearchEngine(storage, level="extended")

        assert [m.matched for m in engine.search("nice")] == [r"|\|ice"]
        with pytest.raises(InvalidSettingValueError):
            LeetspeakSearchEngine(storage, level="nope").search("nice")

    def test_skips_documents_that_are_not_indexed(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/x.pdf", status="error")
        SearchData.add_pdf_page(conn, document_id, 1, "h3ll0")

        assert self._found(storage, "hello") == []


class TestNarrowing:
    @staticmethod
    def _expression(query, level="basic", case_sensitive=False):
        units = LeetspeakSearchEngine._units(query, level, case_sensitive)
        return LeetspeakSearchEngine.narrowing_expression(units)

    def test_lists_every_spelling_of_the_rarest_window(self):
        expression = self._expression("hat")

        assert expression is not None
        phrases = {p.strip('"') for p in expression.split(" OR ")}
        assert phrases == {h + a + t for h in ("h",) for a in ("a", "4", "@") for t in ("t", "7")}

    def test_no_narrowing_for_short_or_space_broken_queries(self):
        assert self._expression("ab") is None
        assert self._expression("a b c d") is None

    def test_agrees_with_a_full_scan(self, conn, storage):
        pages = [
            "say h3ll0 to all",
            "nothing here",
            "the p@55w0rd is",
            "HELLO WORLD",
            "he11o there",
            "w0r1d",
        ]
        for number, text in enumerate(pages):
            SearchData.seed_page(conn, text, path=f"/docs/{number}.pdf")

        for query in ("hello", "password", "h3ll0", "wor1d"):
            units = LeetspeakSearchEngine._units(query, "basic", False)
            assert LeetspeakSearchEngine.narrowing_expression(units) is not None
            whole = re.compile(
                r"(?<!\w)" + "".join(f"(?:{u.pattern})" for u in units) + r"(?!\w)", re.IGNORECASE
            )
            expected = {f"{n}.pdf" for n, text in enumerate(pages) if whole.search(text)}
            found = {
                m.file_name for m in Search.indexed_content(storage, query, engine="leetspeak")
            }
            assert found == expected


class TestLeetspeakLevelOverride:
    @staticmethod
    def _found(storage, query, **kwargs):
        return [
            m.matched for m in Search.indexed_content(storage, query, engine="leetspeak", **kwargs)
        ]

    def test_a_level_given_for_one_search_beats_the_setting(self, conn, storage):
        SearchData.seed_page(conn, r"a |\|ice day and 9ame")

        assert self._found(storage, "nice") == []
        assert self._found(storage, "nice", level="extended") == [r"|\|ice"]
        assert self._found(storage, "game", level="standard") == ["9ame"]
        assert self._found(storage, "game") == []  # the setting is untouched
        assert SearchSettings.get_leetspeak_level(storage) == "basic"

    def test_a_lower_level_than_the_setting_applies_too(self, conn, storage):
        SearchData.seed_page(conn, "a 9ame day")
        SearchSettings.set_leetspeak_level(storage, "extended")

        assert self._found(storage, "game") == ["9ame"]
        assert self._found(storage, "game", level="basic") == []

    def test_an_unknown_level_is_rejected(self, storage):
        with pytest.raises(InvalidSettingValueError):
            Search.indexed_content(storage, "hello", engine="leetspeak", level="insane")

    @pytest.mark.parametrize("engine", ["like", "lexical", "exact", "full-text", "fuzzy"])
    def test_other_engines_reject_a_level(self, storage, engine):
        with pytest.raises(ValueError, match="leetspeak level"):
            Search.indexed_content(storage, "museum", engine=engine, level="basic")

    def test_the_combined_search_passes_it_to_leetspeak(self, conn, storage):
        SearchData.seed_page(conn, "a 9ame day")

        basic = Search.indexed_pages(storage, "game")
        standard = Search.indexed_pages(storage, "game", level="standard")

        assert basic == []
        assert [(p.engine, p.hits[0].matched) for p in standard] == [("leetspeak", "9ame")]

    def test_files_accepts_a_level(self, conn, storage):
        SearchData.seed_page(conn, "a 9ame day")

        files = Search.files(storage, "game", engine="leetspeak", level="standard")

        assert [f.file_name for f in files] == ["museum.pdf"]


class TestLeetspeakOptions:
    def test_resolves_like_the_other_case_aware_engines(self, storage):
        options = Search.resolve_options(storage, "leetspeak", None)

        assert options.engine == "leetspeak"
        assert options.case_sensitive is False
        assert options.threshold is None
        assert options.distance is None
        assert Search.resolve_options(storage, "leetspeak", True).case_sensitive is True

    def test_follows_the_case_sensitive_setting(self, storage):
        SearchSettings.set_case_sensitive(storage, True)

        assert Search.resolve_options(storage, "leetspeak", None).case_sensitive is True

    def test_resolves_the_level_from_the_argument_or_the_setting(self, storage):
        assert Search.resolve_options(storage, "leetspeak", None).level == "basic"
        assert Search.resolve_options(storage, "leetspeak", None, level="Extended").level == (
            "extended"
        )
        SearchSettings.set_leetspeak_level(storage, "standard")
        assert Search.resolve_options(storage, "leetspeak", None).level == "standard"
        assert Search.resolve_options(storage, None, None).level == "standard"  # all
        assert Search.resolve_options(storage, None, None, level="basic").level == "basic"

    def test_a_level_is_only_for_leetspeak_and_all(self, storage):
        with pytest.raises(SearchOptionError) as only:
            Search.resolve_options(storage, "like", None, level="basic")
        with pytest.raises(SearchOptionError) as invalid:
            Search.resolve_options(storage, "leetspeak", None, level="insane")

        assert only.value.option == "level"
        assert "Only the leetspeak and noise-fuzzy engines" in str(only.value)
        assert invalid.value.option == "level"

    def test_other_engines_carry_no_level(self, storage):
        assert Search.resolve_options(storage, "fuzzy", None).level is None
        assert Search.resolve_options(storage, "like", None).level is None

    def test_rejects_fuzzy_and_proximity_options(self, storage):
        with pytest.raises(SearchOptionError) as threshold:
            Search.resolve_options(storage, "leetspeak", None, threshold=0.8)
        with pytest.raises(SearchOptionError) as distance:
            Search.resolve_options(storage, "leetspeak", None, distance=3)

        assert threshold.value.option == "threshold"
        assert distance.value.option == "distance"
