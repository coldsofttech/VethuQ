import pytest
from search_data import SearchData
from vethuq_core.leet import Leet
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines.noise_fuzzy import NoiseFuzzySearchEngine
from vethuq_core.settings import InvalidSettingValueError, SearchSettings, Settings


class TestNoiseSettings:
    def test_defaults_to_low(self, storage):
        assert SearchSettings.get_noise_level(storage) == "low"
        assert SearchSettings.DEFAULT_NOISE == "low"
        assert list(SearchSettings.NOISE_LEVELS) == ["low", "medium", "high"]

    def test_levels_allow_more_noise_each_step(self):
        low, medium, high = SearchSettings.NOISE_LEVELS.values()

        assert low < medium < high
        assert all(gap <= total for gap, total in (low, medium, high))

    def test_set_and_get(self, storage):
        SearchSettings.set_noise_level(storage, " High ")

        assert SearchSettings.get_noise_level(storage) == "high"

    def test_rejects_an_unknown_level(self, storage):
        with pytest.raises(InvalidSettingValueError, match="low, medium, high"):
            SearchSettings.set_noise_level(storage, "loud")

        assert SearchSettings.get_noise_level(storage) == "low"

    def test_a_corrupt_stored_value_falls_back_to_the_default(self, storage):
        Settings.set(storage, SearchSettings.NOISE_KEY, "bogus")

        assert SearchSettings.get_noise_level(storage) == "low"

    def test_is_a_known_engine(self):
        assert "noise-fuzzy" in SearchSettings.ENGINES


def _found(storage, query, **kwargs):
    return [
        m.matched for m in Search.indexed_content(storage, query, engine="noise-fuzzy", **kwargs)
    ]


class TestEachBehaviour:
    @pytest.mark.parametrize(
        ("text", "found"),
        [
            ("say hello to all", ["hello"]),
            ("say helo to all", ["helo"]),  # a missing letter
            ("say hallo to all", ["hallo"]),  # a different letter
            ("say hlelo to all", ["hlelo"]),  # swapped neighbours
            ("say hellp to all", ["hellp"]),
            ("say jello to all", ["jello"]),
            ("say hexxo to all", []),  # two edits are over the balanced threshold
            ("say shellout to all", []),
        ],
    )
    def test_fuzzy_typos(self, conn, storage, text, found):
        SearchData.seed_page(conn, text)

        assert _found(storage, "hello") == found

    @pytest.mark.parametrize(
        ("text", "found"),
        [
            ("say he llo to all", ["he llo"]),  # one stray space
            ("say h.ello to all", ["h.ello"]),
            ("say h e llo to all", ["h e llo"]),  # two, within the total
            ("say h..ello to all", []),  # two in a row: more than low allows
            ("say h e l l o to all", []),  # four in all: more than low allows
            ("say hxello to all", ["hxello"]),  # a letter is not noise - but it is one edit
            ("say hxexlxlxo to all", []),  # ...and four of them are too many
        ],
    )
    def test_noise_at_the_default_low_level(self, conn, storage, text, found):
        SearchData.seed_page(conn, text)

        assert _found(storage, "hello") == found

    @pytest.mark.parametrize(
        ("text", "low", "medium", "high"),
        [
            ("h..e llo", False, True, True),
            ("h e l l o", False, True, True),
            ("h @ e # l l o", False, False, True),  # three noise characters in a row, seven in all
            ("h @ 3 l l 0", False, True, True),
            ("h......ello", False, False, True),  # six in a row
            ("h............ello", False, False, False),  # twelve
        ],
    )
    def test_the_noise_level_sets_how_much_is_skipped(self, conn, storage, text, low, medium, high):
        SearchData.seed_page(conn, f"say {text} to all")

        assert bool(_found(storage, "hello")) is low
        assert bool(_found(storage, "hello", noise="medium")) is medium
        assert bool(_found(storage, "hello", noise="high")) is high

    def test_the_stored_noise_level_is_the_default(self, conn, storage):
        SearchData.seed_page(conn, "say h..e llo to all")
        assert _found(storage, "hello") == []

        SearchSettings.set_noise_level(storage, "medium")

        assert _found(storage, "hello") == ["h..e llo"]
        assert _found(storage, "hello", noise="low") == []  # a per-search level wins

    @pytest.mark.parametrize(
        "text", ["say h3ll0 to all", "say he11o to all", "say h3110 to all", "say HELLO to all"]
    )
    def test_look_alikes(self, conn, storage, text):
        SearchData.seed_page(conn, text)

        assert len(_found(storage, "hello")) == 1

    def test_the_query_may_be_disguised_too(self, conn, storage):
        SearchData.seed_page(conn, "say hello to all")

        assert _found(storage, "h3ll0") == ["hello"]
        assert _found(storage, "h e l l o") == ["hello"]
        assert _found(storage, "h@llo") == ["hello"]  # one edit: @ reads as an a

    def test_password_for_p_at_55_w0rd(self, conn, storage):
        SearchData.seed_page(conn, "the p@55w0rd is secret")

        assert _found(storage, "password") == ["p@55w0rd"]

    def test_all_three_together(self, conn, storage):
        SearchData.seed_page(conn, "the p@ 55 w0rd is secret and the h3l0 sign")

        assert _found(storage, "password") == ["p@ 55 w0rd"]
        assert _found(storage, "hello") == ["h3l0"]  # a look-alike plus a missing letter

    def test_the_letters_of_a_look_alike_symbol_and_an_edit_are_alternatives(self, conn, storage):
        # `@` could be noise or an a: read as an a it costs one edit, which fuzzy allows.
        SearchData.seed_page(conn, "say h@ello to all")

        assert _found(storage, "hello") == ["h@ello"]
        assert _found(storage, "hello", threshold="strict") == []  # 1 edit is under 90%


class TestFuzzySettings:
    def test_the_fuzzy_threshold_applies(self, conn, storage):
        SearchData.seed_page(conn, "visit the Museurn today")

        assert _found(storage, "Museum") == []
        assert _found(storage, "Museum", threshold=0.65) == ["Museurn"]
        SearchSettings.set_fuzzy_threshold(storage, "loose")
        assert _found(storage, "Museum") == ["Museurn"]
        assert _found(storage, "Museum", threshold="strict") == []

    def test_short_queries_must_match_without_edits(self, conn, storage):
        SearchData.seed_page(conn, "a cat and a c@t and a cut")

        assert _found(storage, "cat") == ["cat", "c@t"]  # a look-alike is not an edit

    def test_a_digit_left_after_folding_must_match_exactly(self, conn, storage):
        SearchData.seed_page(conn, "invoice 2025 and invoice 2024 and invoice 2O24")

        # 2025 is one edit away; an O is a look-alike of the 0, so 2O24 is the same text.
        assert _found(storage, "invoice 2024") == ["invoice 2024", "invoice 2O24"]

    def test_a_threshold_is_rejected_by_nobody_but_the_other_engines(self, storage):
        assert Search.resolve_options(storage, "noise-fuzzy", None, threshold=0.7).threshold == 0.7


class TestLevels:
    def test_the_leetspeak_level_decides_which_look_alikes_count(self, conn, storage):
        SearchData.seed_page(conn, "a 9ame and a 8aby")

        assert _found(storage, "game") == []
        assert _found(storage, "game", level="standard") == ["9ame"]
        assert _found(storage, "baby") == []
        assert _found(storage, "baby", level="standard") == ["8aby"]

    def test_the_stored_leetspeak_level_is_the_default(self, conn, storage):
        SearchData.seed_page(conn, "a 9ame today")
        SearchSettings.set_leetspeak_level(storage, "standard")

        assert _found(storage, "game") == ["9ame"]
        assert _found(storage, "game", level="basic") == []

    def test_extended_reads_a_bracket_as_a_c(self, conn, storage):
        SearchData.seed_page(conn, "a [lock on it")

        assert _found(storage, "clock", threshold="strict") == []
        assert _found(storage, "clock", threshold="strict", level="standard") == []
        assert _found(storage, "clock", threshold="strict", level="extended") == ["[lock"]

    def test_multi_character_spellings_are_not_look_alikes_here(self, conn, storage):
        SearchData.seed_page(conn, r"a |\|ice day")

        assert _found(storage, "nice", level="extended") == []  # that is leetspeak's job

    def test_an_unknown_level_is_rejected(self, storage):
        with pytest.raises(InvalidSettingValueError):
            Search.indexed_content(storage, "hello", engine="noise-fuzzy", level="insane")


class TestCaseAndBoundaries:
    def test_case_insensitive_unless_asked(self, conn, storage):
        SearchData.seed_page(conn, "Hello HELLO hello")

        assert _found(storage, "hello") == ["Hello", "HELLO", "hello"]
        assert _found(storage, "hello", case_sensitive=True) == ["Hello", "hello"]  # one edit
        assert _found(storage, "hello", case_sensitive=True, threshold="strict") == ["hello"]

    def test_case_sensitive_look_alikes_still_count(self, conn, storage):
        SearchData.seed_page(conn, "say h3ll0 to all")

        assert _found(storage, "hello", case_sensitive=True) == ["h3ll0"]

    def test_a_match_does_not_start_or_end_inside_a_longer_word(self, conn, storage):
        SearchData.seed_page(conn, "shellout and hellos and ahello and hello!")

        # `hellos` and `ahello` are one edit from the query, as in fuzzy; `shellout` is not.
        assert _found(storage, "hello") == ["hellos", "ahello", "hello"]
        assert _found(storage, "hello", threshold="strict") == ["hello"]

    def test_the_words_of_a_query_are_matched_as_one_run(self, conn, storage):
        SearchData.seed_page(conn, "my p@55w0rd is  ok and m y p a s s w o r d")

        assert _found(storage, "my password") == ["my p@55w0rd"]
        assert _found(storage, "my password", noise="high") == [
            "my p@55w0rd",
            "m y p a s s w o r d",
        ]

    def test_the_words_of_a_query_may_come_from_neighbouring_words(self, conn, storage):
        SearchData.seed_page(conn, "keep to get her for ever")

        assert _found(storage, "together") == ["to get her"]

    def test_matches_do_not_overlap_and_come_in_text_order(self, conn, storage):
        SearchData.seed_page(conn, "hello hello h3ll0")

        matches = Search.indexed_content(storage, "hello", engine="noise-fuzzy")

        assert [m.matched for m in matches] == ["hello", "hello", "h3ll0"]
        assert [m.start for m in matches] == [0, 6, 12]

    def test_reports_where_the_match_is_and_its_context(self, conn, storage):
        SearchData.seed_page(conn, "log in with a h @ 3 l l 0 today")

        (match,) = Search.indexed_content(
            storage, "hello", engine="noise-fuzzy", noise="medium", context_chars=5
        )

        assert match.matched == "h @ 3 l l 0"
        assert (match.before, match.after) == ("th a ", " toda")
        assert (match.start, match.end) == (14, 25)
        assert match.engine == "noise-fuzzy"

    def test_searches_image_pages_and_text_across_lines(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/scan.png", "image")
        SearchData.add_image_page(conn, document_id, "say h\n3ll0 now")

        assert _found(storage, "hello") == ["h 3ll0"]

    def test_unicode_is_kept(self, conn, storage):
        SearchData.seed_page(conn, "Café and c@fé and cafe")

        assert _found(storage, "café") == ["Café", "c@fé"]  # cafe is an edit away: 75%

    def test_skips_documents_that_are_not_indexed(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/x.pdf", status="error")
        SearchData.add_pdf_page(conn, document_id, 1, "h3ll0")

        assert _found(storage, "hello") == []


class TestShortAndOddQueries:
    def test_there_is_no_minimum_length(self, conn, storage):
        SearchData.seed_page(conn, "go to g0 or good or 4 or a")

        assert _found(storage, "go") == ["go", "g0"]
        assert _found(storage, "a") == ["4", "a"]
        assert _found(storage, "4") == ["4", "a"]

    def test_a_query_of_only_noise_matches_nothing(self, conn, storage):
        SearchData.seed_page(conn, "a ... page , with # symbols")

        assert _found(storage, "") == []
        assert _found(storage, "   ") == []
        assert _found(storage, "...") == []
        assert _found(storage, "#-#") == []

    def test_rejects_a_distance(self, storage):
        with pytest.raises(ValueError, match="distance"):
            Search.indexed_content(storage, "hello", engine="noise-fuzzy", distance=3)

    def test_other_engines_reject_a_noise_level(self, storage):
        for engine in ("like", "lexical", "exact", "full-text", "fuzzy", "proximity", "leetspeak"):
            with pytest.raises(ValueError, match="noise level"):
                Search.indexed_content(storage, "museum", engine=engine, noise="low")

    def test_an_unknown_noise_level_is_rejected(self, storage):
        with pytest.raises(InvalidSettingValueError):
            Search.indexed_content(storage, "hello", engine="noise-fuzzy", noise="loud")


class TestScoring:
    def test_cleaner_text_ranks_first(self, conn, storage):
        SearchData.seed_page(conn, "h.ello", path="/docs/a_noise.pdf")
        SearchData.seed_page(conn, "h3llo", path="/docs/b_lookalike.pdf")
        SearchData.seed_page(conn, "hallo", path="/docs/c_typo.pdf")
        SearchData.seed_page(conn, "hello", path="/docs/d_plain.pdf")

        matches = Search.indexed_content(storage, "hello", engine="noise-fuzzy")

        assert [m.file_name for m in matches] == [
            "d_plain.pdf",
            "a_noise.pdf",
            "b_lookalike.pdf",
            "c_typo.pdf",
        ]
        assert matches[0].score == 1.0
        scores = [m.score for m in matches]
        assert scores == sorted(scores, reverse=True)
        assert all(0 < score <= 1 for score in scores)

    def test_each_cost_lowers_the_score(self, conn, storage):
        cases = {"hello": 1.0, "h3llo": None, "he llo": None, "helo": None}
        for number, text in enumerate(cases):
            SearchData.seed_page(conn, text, path=f"/docs/{number}.pdf")

        by_text = {
            m.matched: m.score
            for m in Search.indexed_content(storage, "hello", engine="noise-fuzzy")
        }

        assert by_text["hello"] == 1.0
        assert by_text["h3llo"] == pytest.approx(1 - NoiseFuzzySearchEngine.LOOKALIKE_PENALTY)
        assert by_text["he llo"] == pytest.approx(1 - NoiseFuzzySearchEngine.NOISE_PENALTY)
        assert by_text["helo"] == pytest.approx(1 - NoiseFuzzySearchEngine.EDIT_PENALTY)

    def test_a_disguised_query_scores_its_own_spelling_highest(self, conn, storage):
        SearchData.seed_page(conn, "h3ll0", path="/docs/b_same.pdf")
        SearchData.seed_page(conn, "hello", path="/docs/a_plain.pdf")

        matches = Search.indexed_content(storage, "h3ll0", engine="noise-fuzzy")

        assert [m.file_name for m in matches] == ["b_same.pdf", "a_plain.pdf"]
        assert matches[0].score == 1.0


class TestNarrowing:
    def test_no_edits_means_the_skeleton_must_appear_whole(self):
        assert NoiseFuzzySearchEngine.narrowing_expression("heiio", 0) == '"heiio"'

    def test_edits_leave_any_trigram_enough_when_the_word_is_long(self):
        expression = NoiseFuzzySearchEngine.narrowing_expression("museums", 1)

        assert expression == '"eum" OR "mus" OR "seu" OR "ums" OR "use"'

    def test_it_does_not_narrow_when_that_would_be_unsound(self):
        assert NoiseFuzzySearchEngine.narrowing_expression("heiio", 1) is None  # 5 - 2 <= 3 * 1
        assert NoiseFuzzySearchEngine.narrowing_expression("ab", 0) is None  # under 3 characters
        assert NoiseFuzzySearchEngine.narrowing_expression("", 0) is None

    def test_with_no_edits_the_stretches_are_the_occurrences(self):
        stretches = NoiseFuzzySearchEngine.candidate_stretches

        assert stretches("heiio", 0, "sayheiiotoaheiio") == [(3, 8), (11, 16)]
        assert stretches("heiio", 0, "sayhaiiotoaii") == []
        assert stretches("heiio", 0, "heiioheiio") == [(0, 10)]  # touching ones are joined

    def test_with_edits_the_stretches_are_where_the_query_is_close(self):
        stretches = NoiseFuzzySearchEngine.candidate_stretches

        found = stretches("heiio", 1, "xxxxxxsayhaiiotoaiixxxxxxxxxxxxx")
        assert found and all(low <= 9 and high >= 15 for low, high in found)
        assert stretches("heiio", 1, "xxxxxxxxxxxxxxxx") == []
        assert stretches("password", 2, "quiet museum notes about nothing") == []

    def test_a_long_query_needs_most_of_its_pieces_close_together(self):
        stretches = NoiseFuzzySearchEngine.candidate_stretches

        assert stretches("internationai", 2, "intxrnatioonai" + "x" * 40) != []
        assert stretches("internationai", 2, "inxxtexxnaxxtioxxnaxxxxxx") == []

    def test_an_unrecorded_skeleton_cannot_be_ruled_out(self):
        assert NoiseFuzzySearchEngine.candidate_stretches("heiio", 1, "") is None
        assert NoiseFuzzySearchEngine.candidate_stretches("heiio", 0, "") is None

    def test_allowed_edits(self):
        edits = NoiseFuzzySearchEngine.allowed_edits

        assert edits("heiio", 0.8) == 1
        assert edits("heiio", 0.9) == 0
        assert edits("heiio", 0.65) == 2
        assert edits("hei", 0.5) == 0  # under four characters
        assert edits("zoza", 0.5) == 2
        assert edits("2oza", 0.5) == 0  # a digit that wasn't folded
        assert edits("password", 0.8) == 2  # never more than two

    @pytest.mark.parametrize("query", ["hello", "password", "h3ll0", "museum", "my password"])
    @pytest.mark.parametrize("threshold", ["strict", "balanced", "loose"])
    def test_narrowing_never_loses_a_match(self, conn, storage, monkeypatch, query, threshold):
        pages = [
            "say h3ll0 to all",
            "nothing relevant here",
            "the p@55w0rd is secret",
            "he llo there and h.e.l.l.o again",
            "visit the Muzeum and the Museurn",
            "my p a s s w o r d is gone",
            "HELLO WORLD and hallo",
            "a quiet page about museums",
        ]
        for number, text in enumerate(pages):
            SearchData.seed_page(conn, text, path=f"/docs/{number}.pdf")
        narrowed = [
            (m.file_name, m.matched)
            for m in Search.indexed_content(
                storage, query, engine="noise-fuzzy", threshold=threshold, noise="high"
            )
        ]

        monkeypatch.setattr(
            NoiseFuzzySearchEngine, "narrowing_expression", staticmethod(lambda *_: None)
        )
        monkeypatch.setattr(
            NoiseFuzzySearchEngine, "candidate_stretches", staticmethod(lambda *_: None)
        )
        everything = [
            (m.file_name, m.matched)
            for m in Search.indexed_content(
                storage, query, engine="noise-fuzzy", threshold=threshold, noise="high"
            )
        ]

        assert narrowed == everything

    def test_pages_without_a_recorded_skeleton_are_still_searched(self, conn, storage):
        SearchData.seed_page(conn, "say h3ll0 to all")
        conn.execute("UPDATE pdf_pages SET noise_text = ''")
        conn.commit()

        assert _found(storage, "hello") == ["h3ll0"]


class TestOptions:
    def test_resolves_like_fuzzy_plus_level_and_noise(self, storage):
        options = Search.resolve_options(storage, "noise-fuzzy", None)

        assert options.engine == "noise-fuzzy"
        assert options.case_sensitive is False
        assert options.threshold == 0.8
        assert options.distance is None
        assert options.level == "basic"
        assert options.noise == "low"

    def test_arguments_beat_the_settings(self, storage):
        SearchSettings.set_noise_level(storage, "high")

        options = Search.resolve_options(
            storage, "noise-fuzzy", True, threshold="loose", level="Standard", noise="Medium"
        )

        assert options == ("noise-fuzzy", True, 0.65, None, "standard", "medium")
        assert Search.resolve_options(storage, "noise-fuzzy", None).noise == "high"

    def test_follows_the_case_sensitive_setting(self, storage):
        SearchSettings.set_case_sensitive(storage, True)

        assert Search.resolve_options(storage, "noise-fuzzy", None).case_sensitive is True

    def test_a_noise_level_is_only_for_noise_fuzzy_and_all(self, storage):
        for engine in ("like", "fuzzy", "leetspeak", "proximity"):
            with pytest.raises(SearchOptionError) as error:
                Search.resolve_options(storage, engine, None, noise="low")
            assert error.value.option == "noise"
            assert "Only the noise-fuzzy engine" in str(error.value)
        with pytest.raises(SearchOptionError) as invalid:
            Search.resolve_options(storage, "noise-fuzzy", None, noise="loud")
        assert invalid.value.option == "noise"

        assert Search.resolve_options(storage, "all", None, noise="medium").noise == "medium"
        assert Search.resolve_options(storage, "all", None).noise == "low"

    def test_other_engines_carry_no_noise(self, storage):
        assert Search.resolve_options(storage, "fuzzy", None).noise is None
        assert Search.resolve_options(storage, "leetspeak", None).noise is None

    def test_threshold_and_level_are_also_for_noise_fuzzy(self, storage):
        assert Search.resolve_options(storage, "noise-fuzzy", None, threshold=0.9).threshold == 0.9
        assert Search.resolve_options(storage, "noise-fuzzy", None, level="extended").level == (
            "extended"
        )
        with pytest.raises(SearchOptionError, match="noise-fuzzy"):
            Search.resolve_options(storage, "like", None, threshold=0.9)
        with pytest.raises(SearchOptionError, match="noise-fuzzy"):
            Search.resolve_options(storage, "like", None, level="basic")

    def test_the_skeleton_helper_is_what_the_index_uses(self):
        assert Leet.skeleton("h @ 3 l l 0") == "haeiio"
