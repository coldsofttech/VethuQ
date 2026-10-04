"""Pins what the normalizers and the full-text tokenizer do to English (and other non-Telugu)
text, so the Telugu work cannot change it.

The expected values were recorded from the code before any language-specific handling existed.
If one of these fails, a change has altered how existing text is searched: fix the change, do not
update the table.
"""

import pytest
from vethuq_core.search.engines.fulltext import FullTextSearchEngine
from vethuq_core.search.normalizers import Normalizers
from vethuq_core.search.normalizers.leetspeak import Leet
from vethuq_core.search.normalizers.unicode import UnicodeNormalizer

# text -> (unicode basic, unicode full, skeleton, index form)
FOLDING = {
    "Hello World": ("Hello World", "Hello World", "heiioworid", "heiio worid"),
    "Café Müller": ("Café Müller", "Cafe Muller", "cafemuiier", "cafe muiier"),
    "naïve résumé": ("naïve résumé", "naive resume", "naiveresume", "naive resume"),
    "ﬁnance Ａ１": ("ﬁnance Ａ１", "finance A1", "financeai", "finance ai"),
    "h3ll0 w0rld p@55w0rd": (
        "h3ll0 w0rld p@55w0rd",
        "h3ll0 w0rld p@55w0rd",
        "heiioworidpassword",
        "heiio worid password",
    ),
    "Invoice #2024-001 total: $1,234.50": (
        "Invoice #2024-001 total: $1,234.50",
        "Invoice #2024-001 total: $1,234.50",
        "invoicezozaooitotaisizeaso",
        "invoice #zoza-ooi totai: si,zea.so",
    ),
    "école": ("école", "ecole", "ecoie", "ecoie"),
    "The QUICK brown fox": (
        "The QUICK brown fox",
        "The QUICK brown fox",
        "thequickbrownfox",
        "the quick brown fox",
    ),
    "O'Brien's": ("O'Brien's", "O'Brien's", "obriens", "o'brien's"),
    "日本語 mixed text": (
        "日本語 mixed text",
        "日本語 mixed text",
        "日本語mixedtext",
        "日本語 mixed text",
    ),
    "": ("", "", "", ""),
}

TERMS = {
    "Hello World": ['"Hello"', '"World"'],
    "Café Müller": ['"Café"', '"Müller"'],
    "state-of-the-art": ['"state of the art"'],
    "O'Brien's": ['"O Brien s"'],
    "museum": ['"museum"'],
    '"annual report" mus*': ['"annual report"', '"mus" *'],
    "AND OR NEAR(a b)": ['"AND"', '"OR"', '"NEAR a"', '"b"'],
    "foo-bar:baz": ['"foo bar baz"'],
    "*": [],
    "it's 3.14": ['"it s"', '"3 14"'],
}


@pytest.mark.parametrize("text", FOLDING)
def test_unicode_and_skeleton_folding_is_unchanged(text):
    basic, full, skeleton, index_form = FOLDING[text]
    unicode_normalizer = UnicodeNormalizer()

    assert unicode_normalizer.fold(text, "basic").text == basic
    assert unicode_normalizer.fold(text, "full").text == full
    assert Leet.skeleton(text) == skeleton
    assert Normalizers.index_form(text) == index_form


@pytest.mark.parametrize("query", TERMS)
def test_full_text_terms_are_unchanged(query):
    assert FullTextSearchEngine.parse_terms(query) == TERMS[query]
