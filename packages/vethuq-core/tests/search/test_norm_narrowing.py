"""The norm index only narrows: results never depend on it."""

import pytest
from search_data import SearchData
from vethuq_core.search import Search

PAGES = [
    "a Café and a cafe and a café",
    "the r3sum3 and the résumé of a h3ll0 world",
    "Ｆｉｎｅ ﬁne fine, p@55w0rd and password",
    "h . e l l o and h e l l o and hallo",
    "something else entirely, nothing to find",
    "INVOICE Inv01c3 invoice no. 42",
]
QUERIES = ["cafe", "café", "resume", "hello", "fine", "password", "invoice", "helo", "Invoice"]


def _results(storage, query, engine, **kwargs):
    return [
        (m.file_path, m.page_number, m.start, m.end)
        for m in Search.indexed_content(storage, query, engine=engine, **kwargs)
    ]


@pytest.mark.parametrize("engine", ["like", "exact", "fuzzy", "noise-fuzzy"])
@pytest.mark.parametrize("unicode", [None, "off", "basic", "full"])
def test_results_do_not_depend_on_the_index(conn, storage, engine, unicode):
    for number, text in enumerate(PAGES):
        SearchData.seed_page(conn, text, path=f"/docs/p{number}.pdf")
    with_index = {q: _results(storage, q, engine, unicode=unicode) for q in QUERIES}
    # Pages without recorded text are always candidates: the same as scanning them all.
    conn.execute("UPDATE pdf_pages SET norm_text = '', noise_text = ''")
    conn.execute("UPDATE image_pages SET norm_text = '', noise_text = ''")
    without_index = {q: _results(storage, q, engine, unicode=unicode) for q in QUERIES}

    assert with_index == without_index
    assert any(with_index.values())


def test_a_decomposed_accent_is_found_by_default(conn, storage):
    SearchData.seed_page(conn, "a visit to the café today")

    assert [m.matched for m in Search.indexed_content(storage, "café", engine="like")] == ["café"]
    assert [m.matched for m in Search.indexed_content(storage, "café", engine="exact")] == ["café"]


def test_the_defaults_per_engine(conn, storage):
    SearchData.seed_page(conn, "a visit to the Café today")

    assert Search.indexed_content(storage, "cafe", engine="like") == []
    assert Search.indexed_content(storage, "Cafe", engine="exact") == []
    assert [m.matched for m in Search.indexed_content(storage, "Cafe", engine="fuzzy")] == ["Café"]
    assert [m.matched for m in Search.indexed_content(storage, "cafe", engine="noise-fuzzy")] == [
        "Café"
    ]
