import pytest
from search_data import SearchData
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.settings import InvalidSettingValueError, SearchSettings, Settings

DECOMPOSED_CAFE = "café"  # an e and a combining accent, rendered as "café"


class TestUnicodeSettings:
    def test_defaults_to_auto(self, storage):
        assert SearchSettings.get_unicode(storage) == "auto"
        assert SearchSettings.UNICODE_LEVELS == ("off", "basic", "full")
        assert SearchSettings.UNICODE_VALUES == ("auto", "off", "basic", "full")

    def test_set_and_get(self, storage):
        for value in ("off", "Basic", "full", "auto"):
            SearchSettings.set_unicode(storage, value)
            assert SearchSettings.get_unicode(storage) == value.lower()

    def test_rejects_unknown_values(self, storage):
        with pytest.raises(InvalidSettingValueError, match="off, basic, full"):
            SearchSettings.set_unicode(storage, "nfd")
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.parse_unicode("auto")  # only the stored setting can be `auto`
        assert SearchSettings.get_unicode(storage) == "auto"

    def test_a_corrupt_stored_value_reads_as_auto(self, storage):
        Settings.set(storage, SearchSettings.NORMALIZE_UNICODE_KEY, "bogus")

        assert SearchSettings.get_unicode(storage) == "auto"

    def test_resolve_uses_the_engines_default_on_auto(self, storage):
        assert SearchSettings.resolve_unicode(storage, "off") == "off"
        assert SearchSettings.resolve_unicode(storage, "full") == "full"
        SearchSettings.set_unicode(storage, "basic")
        assert SearchSettings.resolve_unicode(storage, "off") == "basic"
        assert SearchSettings.UNICODE_DEFAULTS == {
            "exact": "basic",
            "like": "basic",
            "fuzzy": "full",
            "noise-fuzzy": "full",
        }


def _found(storage, query, engine, **kwargs):
    return [m.matched for m in Search.indexed_content(storage, query, engine=engine, **kwargs)]


class TestLike:
    def test_off_asks_for_the_text_as_typed(self, conn, storage):
        SearchData.seed_page(conn, "a café and a cafe")

        assert _found(storage, "cafe", "like", unicode="off") == ["cafe"]
        assert _found(storage, "café", "like", unicode="off") == ["café"]

    def test_basic_composes_characters_but_keeps_accents(self, conn, storage):
        SearchData.seed_page(conn, f"a {DECOMPOSED_CAFE} and a cafe")

        assert _found(storage, "café", "like", unicode="off") == []  # written differently
        assert _found(storage, "café", "like") == [DECOMPOSED_CAFE]  # basic is the default
        assert _found(storage, "cafe", "like") == ["cafe"]  # ...and keeps accents
        assert _found(storage, "café", "like", unicode="basic") == [DECOMPOSED_CAFE]
        assert _found(storage, "cafe", "like", unicode="basic") == ["cafe"]

    def test_full_folds_accents_too(self, conn, storage):
        SearchData.seed_page(conn, f"a café and a {DECOMPOSED_CAFE} and a cafe")

        assert _found(storage, "cafe", "like", unicode="full") == ["café", DECOMPOSED_CAFE, "cafe"]
        assert _found(storage, "café", "like", unicode="full") == ["café", DECOMPOSED_CAFE, "cafe"]

    def test_full_folds_compatibility_forms(self, conn, storage):
        SearchData.seed_page(conn, "the ﬁne ＡBC x²")

        assert _found(storage, "fine", "like", unicode="full") == ["ﬁne"]
        assert _found(storage, "abc", "like", unicode="full") == ["ＡBC"]
        assert _found(storage, "x2", "like", unicode="full") == ["x²"]

    def test_reports_the_original_text_and_where_it_is(self, conn, storage):
        SearchData.seed_page(conn, f"eat at the {DECOMPOSED_CAFE} today")

        (match,) = Search.indexed_content(
            storage, "cafe", engine="like", unicode="full", context_chars=4
        )

        assert match.matched == DECOMPOSED_CAFE
        assert (match.before, match.after) == ("the ", " tod")
        assert (match.start, match.end) == (11, 16)

    def test_the_stored_setting_is_the_default(self, conn, storage):
        SearchData.seed_page(conn, "a café")

        SearchSettings.set_unicode(storage, "full")

        assert _found(storage, "cafe", "like") == ["café"]
        assert _found(storage, "cafe", "like", unicode="off") == []

    def test_combines_with_case_and_look_alikes(self, conn, storage):
        SearchData.seed_page(conn, "Visit the CAFÉ and the c@fé")

        assert _found(storage, "cafe", "like", unicode="full") == ["CAFÉ"]
        assert _found(storage, "cafe", "like", unicode="full", level="basic") == [
            "CAFÉ",
            "c@fé",
        ]
        assert _found(storage, "cafe", "like", unicode="full", case_sensitive=True) == []
        assert _found(
            storage, "cafe", "like", unicode="full", level="basic", case_sensitive=True
        ) == ["c@f\u00e9"]

    def test_finds_across_image_pages_and_other_documents(self, conn, storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/scan.png", "image")
        SearchData.add_image_page(conn, document_id, "naïve café")

        assert _found(storage, "naive", "like", unicode="full") == ["naïve"]

    def test_an_invalid_level_is_rejected(self, storage):
        with pytest.raises(InvalidSettingValueError):
            Search.indexed_content(storage, "cafe", engine="like", unicode="nfd")


class TestExact:
    def test_as_typed_unless_asked(self, conn, storage):
        SearchData.seed_page(conn, "Café and Cafe")

        assert _found(storage, "Cafe", "exact") == ["Cafe"]

    def test_the_stored_setting_never_loosens_it(self, conn, storage):
        SearchData.seed_page(conn, "Café and Cafe")
        SearchSettings.set_unicode(storage, "full")

        assert _found(storage, "Cafe", "exact") == ["Cafe"]

    def test_a_unicode_level_asked_for_applies_but_case_is_still_matched(self, conn, storage):
        SearchData.seed_page(conn, f"Café and Cafe and {DECOMPOSED_CAFE.title()} and café")

        assert _found(storage, "Cafe", "exact", unicode="full") == [
            "Café",
            "Cafe",
            DECOMPOSED_CAFE.title(),
        ]
        assert _found(storage, "Café", "exact", unicode="basic") == [
            "Café",
            DECOMPOSED_CAFE.title(),
        ]

    def test_still_a_whole_word(self, conn, storage):
        SearchData.seed_page(conn, "Cafés and Café")

        assert _found(storage, "Cafe", "exact", unicode="full") == ["Café"]


class TestFuzzy:
    def test_an_accent_is_an_edit_unless_folded(self, conn, storage):
        SearchData.seed_page(conn, "a visit to the Café today")

        assert _found(storage, "Cafe", "fuzzy", unicode="basic") == []  # one edit in four: 75%
        assert _found(storage, "Cafe", "fuzzy", unicode="full") == ["Café"]
        assert _found(storage, "Cafe", "fuzzy") == ["Café"]  # full is its default

    def test_the_match_is_the_original_word(self, conn, storage):
        SearchData.seed_page(conn, f"eat at the {DECOMPOSED_CAFE} today")

        (match,) = Search.indexed_content(storage, "cafe", engine="fuzzy", unicode="full")

        assert match.matched == DECOMPOSED_CAFE
        assert match.score == 1.0

    def test_still_tolerates_typos_after_folding(self, conn, storage):
        SearchData.seed_page(conn, "the Muséum of art")

        assert _found(storage, "Muzeum", "fuzzy", unicode="full") == ["Muséum"]

    def test_the_stored_setting_applies(self, conn, storage):
        SearchData.seed_page(conn, "a visit to the Café today")
        SearchSettings.set_unicode(storage, "basic")

        assert _found(storage, "Cafe", "fuzzy") == []


class TestNoiseFuzzy:
    def test_folds_accents_then_hides_them_in_noise(self, conn, storage):
        SearchData.seed_page(conn, "visit the c a f é today")

        assert _found(storage, "cafe", "noise-fuzzy", noise="medium", unicode="off") == []  # a typo
        assert _found(storage, "cafe", "noise-fuzzy", noise="medium", unicode="full") == ["c a f é"]

    def test_reports_the_original_text(self, conn, storage):
        SearchData.seed_page(conn, f"eat at the {DECOMPOSED_CAFE} today")

        (match,) = Search.indexed_content(
            storage, "cafe", engine="noise-fuzzy", unicode="full", context_chars=4
        )

        assert match.matched == DECOMPOSED_CAFE
        assert (match.start, match.end) == (11, 16)
        assert (match.before, match.after) == ("the ", " tod")

    def test_with_look_alikes_and_a_normalized_query(self, conn, storage):
        SearchData.seed_page(conn, "the résumé and the r3sum3")

        assert _found(storage, "resume", "noise-fuzzy", unicode="full") == [
            "résumé",
            "r3sum3",
        ]

    def test_pages_are_found_without_the_skeleton_index(self, conn, storage):
        SearchData.seed_page(conn, "visit the café")

        # The recorded skeleton knows nothing of accents, so a normalized search reads the pages.
        assert _found(storage, "cafe", "noise-fuzzy", unicode="full") == ["café"]


class TestOtherEngines:
    @pytest.mark.parametrize("engine", ["lexical", "full-text", "proximity"])
    def test_have_no_unicode_setting(self, storage, engine):
        with pytest.raises(ValueError, match="no unicode setting"):
            Search.indexed_content(storage, "payment termination", engine=engine, unicode="full")

    def test_the_stored_setting_does_not_reach_them(self, conn, storage):
        SearchData.seed_page(conn, "the payment termination clause")
        SearchSettings.set_unicode(storage, "full")

        assert _found(storage, "payment", "lexical") == ["payment"]
        assert _found(storage, "payment", "full-text") == ["payment"]


class TestCombinedSearch:
    def test_the_stored_setting_reaches_the_engines_that_take_it(self, conn, storage):
        # `full-text` already folds accents; it doesn't fold full-width letters.
        SearchData.seed_page(conn, "the \uff21\uff22\uff23 sign")
        SearchSettings.set_unicode(storage, "off")
        assert Search.indexed_pages(storage, "abc") == []

        SearchSettings.set_unicode(storage, "full")

        (page,) = Search.indexed_pages(storage, "abc")
        assert page.hits[0].matched == "\uff21\uff22\uff23"

    def test_the_argument_beats_the_setting(self, conn, storage):
        SearchData.seed_page(conn, "the \uff21\uff22\uff23 sign")
        SearchSettings.set_unicode(storage, "full")

        assert Search.indexed_pages(storage, "abc", unicode="off") == []
        assert Search.indexed_pages(storage, "abc", unicode="full")


class TestOptions:
    def test_resolves_from_the_argument_or_setting_or_the_engines_default(self, storage):
        assert Search.resolve_options(storage, "like", None).unicode == "basic"
        assert Search.resolve_options(storage, "fuzzy", None).unicode == "full"
        assert Search.resolve_options(storage, "noise-fuzzy", None).unicode == "full"
        assert Search.resolve_options(storage, None, None).unicode is None  # all: each its own
        SearchSettings.set_unicode(storage, "off")
        assert Search.resolve_options(storage, "like", None).unicode == "off"
        assert Search.resolve_options(storage, "like", None, unicode="Full").unicode == "full"
        assert Search.resolve_options(storage, None, None).unicode == "off"  # all
        assert Search.resolve_options(storage, "fuzzy", None).unicode == "off"
        assert Search.resolve_options(storage, "noise-fuzzy", None).unicode == "off"

    def test_exact_takes_it_only_when_asked(self, storage):
        SearchSettings.set_unicode(storage, "full")

        assert Search.resolve_options(storage, "exact", None).unicode == "basic"
        assert Search.resolve_options(storage, "exact", None, unicode="basic").unicode == "basic"

    def test_other_engines_carry_none(self, storage):
        for engine in ("lexical", "full-text", "proximity"):
            assert Search.resolve_options(storage, engine, None).unicode is None

    def test_other_engines_reject_it(self, storage):
        for engine in ("lexical", "full-text", "proximity"):
            with pytest.raises(SearchOptionError) as error:
                Search.resolve_options(storage, engine, None, unicode="full")
            assert error.value.option == "unicode"
            assert "Only the like, exact, fuzzy and noise-fuzzy engines" in str(error.value)

    def test_an_invalid_value_names_the_levels(self, storage):
        with pytest.raises(SearchOptionError, match="off, basic, full") as error:
            Search.resolve_options(storage, "like", None, unicode="nfd")
        assert error.value.option == "unicode"
