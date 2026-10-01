from vethuq_ui.search_view import SearchView


def _rows(view: SearchView) -> list[tuple[str, str]]:
    return [
        (view.tree.item(iid, "text").strip(), view.tree.item(iid, "values")[0])
        for iid in view.tree.get_children()
    ]


class TestSearchView:
    def test_starts_with_a_placeholder_in_the_entry(self, window):
        assert window.search.var.get() == SearchView.PLACEHOLDER

    def test_focusing_the_entry_clears_the_placeholder_and_leaving_restores_it(self, window):
        window.search.entry.event_generate("<FocusIn>")
        assert window.search.var.get() == ""

        window.search.entry.event_generate("<FocusOut>")
        assert window.search.var.get() == SearchView.PLACEHOLDER

    def test_lists_one_row_per_matching_file(self, window, add_source, seed_document, tmp_path):
        source_id = add_source()
        seed_document(window.conn, source_id, tmp_path / "docs" / "a.pdf", "quarterly budget")
        seed_document(window.conn, source_id, tmp_path / "docs" / "b.pdf", "unrelated text")
        window.search.var.set("budget")

        window.search.on_search()

        assert _rows(window.search) == [("a.pdf", str(tmp_path / "docs" / "a.pdf"))]

    def test_empty_or_placeholder_query_clears_the_results(
        self, window, add_source, seed_document, tmp_path
    ):
        source_id = add_source()
        seed_document(window.conn, source_id, tmp_path / "docs" / "a.pdf", "quarterly budget")
        window.search.var.set("budget")
        window.search.on_search()
        assert _rows(window.search)

        window.search.var.set(SearchView.PLACEHOLDER)
        window.search.on_search()

        assert _rows(window.search) == []

    def test_flags_a_duplicate_copy_in_its_name(self, window, add_source, seed_document, tmp_path):
        source_id = add_source()
        original = seed_document(window.conn, source_id, tmp_path / "docs" / "a.pdf", "budget")
        duplicate = seed_document(window.conn, source_id, tmp_path / "docs" / "b.pdf", None)
        # The duplicate shares the original's logical document, so reuses its OCR text.
        window.conn.execute(
            "UPDATE document_index SET document_id = (SELECT document_id FROM document_index "
            "WHERE id = ?) WHERE id = ?",
            (original, duplicate),
        )
        window.conn.commit()
        window.search.var.set("budget")

        window.search.on_search()

        assert sorted(name for name, _ in _rows(window.search)) == ["a.pdf", "b.pdf (duplicate)"]

    def test_long_names_are_truncated_but_kept_in_full_for_the_tooltip(
        self, window, add_source, seed_document, tmp_path
    ):
        source_id = add_source()
        long_name = "x" * 50 + ".pdf"
        seed_document(window.conn, source_id, tmp_path / "docs" / long_name, "budget")
        window.search.var.set("budget")

        window.search.on_search()

        shown = _rows(window.search)[0][0]
        assert shown.endswith("\N{HORIZONTAL ELLIPSIS}")
        assert len(shown) == SearchView.MAX_DISPLAYED_NAME_CHARS
        assert window.search.full_names[str(window.search.tree.get_children()[0])] == long_name

    def test_truncate_name_keeps_short_names_whole(self):
        assert SearchView.truncate_name("a.pdf") == " a.pdf"
        assert SearchView.truncate_name("abcdef", max_chars=4) == " abc\N{HORIZONTAL ELLIPSIS}"
