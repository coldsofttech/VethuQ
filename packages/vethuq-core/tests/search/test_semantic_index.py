import pytest
from search_data import SearchData
from vethuq_core.semantic import SemanticIndex


@pytest.fixture
def model(embedder):
    return embedder.model


def _page(conn, text, path="/docs/a.pdf", number=1, source_id=None):
    source_id = source_id or SearchData.add_source(conn, path + ".src")
    document_id = SearchData.add_document(conn, source_id, path)
    SearchData.add_pdf_page(conn, document_id, number, text)
    return document_id


class TestSync:
    def test_embeds_every_searchable_page_once(self, conn, storage, embedder, model):
        _page(conn, "Refund policy for customers.", "/docs/a.pdf")
        document = _page(conn, "The museum opens at nine.", "/docs/b.pdf")
        SearchData.add_image_page(
            conn, SearchData.add_document(conn, 1, "/docs/c.png", "image"), "A cat."
        )

        result = SemanticIndex.sync(storage, embedder)

        assert result.pages == 3 and result.chunks == 3
        assert SemanticIndex.status(storage, model).embedded == 3
        assert document

        embedded = len(embedder.passages)
        assert SemanticIndex.sync(storage, embedder).pages == 0
        assert len(embedder.passages) == embedded

    def test_status_counts_pages_and_chunks(self, conn, storage, embedder, model):
        _page(conn, "Alpha beta gamma. " * 60)
        before = SemanticIndex.status(storage, model)
        assert (before.pages, before.embedded, before.pending) == (1, 0, 1)

        SemanticIndex.sync(storage, embedder)

        after = SemanticIndex.status(storage, model)
        assert (after.pages, after.embedded, after.pending) == (1, 1, 0)
        assert after.chunks > 1

    def test_vectors_are_stored_as_float32_blobs(self, conn, storage, embedder, model):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)

        (row,) = storage.list_semantic_chunks(model)

        assert len(row["vector"]) == 4 * embedder.embed_query("x").shape[0]
        assert (row["kind"], row["start_char"], row["end_char"]) == ("pdf", 0, 14)

    def test_a_page_without_text_is_recorded_so_it_is_not_tried_again(
        self, conn, storage, embedder, model
    ):
        _page(conn, "   ")
        assert SemanticIndex.sync(storage, embedder).pages == 1
        assert SemanticIndex.sync(storage, embedder).pages == 0
        assert SemanticIndex.status(storage, model).chunks == 0

    def test_changed_text_is_embedded_again(self, conn, storage, embedder, model):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)
        conn.execute("UPDATE pdf_pages SET ocr_text = 'The museum is closed.'")
        conn.commit()

        assert SemanticIndex.status(storage, model).pending == 1
        SemanticIndex.sync(storage, embedder)

        (row,) = storage.list_semantic_chunks(model)
        assert embedder.passages[-1] == "The museum is closed."
        assert row["end_char"] == len("The museum is closed.")

    def test_rewriting_a_page_with_the_same_text_keeps_its_embedding(
        self, conn, storage, embedder, model
    ):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)
        conn.execute("UPDATE pdf_pages SET confidence = 0.5, ocr_text = ocr_text")
        conn.commit()

        assert SemanticIndex.status(storage, model).pending == 0

    def test_deleted_pages_lose_their_embeddings(self, conn, storage, embedder, model):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)

        conn.execute("DELETE FROM pdf_pages")
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM semantic_pages").fetchone()[0] == 0

    def test_only_pages_search_can_see_are_embedded(self, conn, storage, embedder, model):
        source = SearchData.add_source(conn, "/live")
        visible = SearchData.add_document(conn, source, "/live/ok.pdf")
        SearchData.add_pdf_page(conn, visible, 1, "Refund policy.")
        SearchData.add_pdf_page(
            conn, SearchData.add_document(conn, source, "/live/bad.pdf", status="error"), 1, "No."
        )
        SearchData.add_pdf_page(
            conn, SearchData.add_document(conn, source, "/live/new.pdf", status="pending"), 1, "No!"
        )
        conn.execute("UPDATE sources SET is_active = 0 WHERE path = ?", ("/live",))
        conn.commit()
        assert SemanticIndex.status(storage, model).pages == 0

        conn.execute("UPDATE sources SET is_active = 1")
        conn.commit()
        assert SemanticIndex.status(storage, model).pages == 1

    def test_reports_progress_after_each_batch(self, conn, storage, embedder):
        for number in range(SemanticIndex.PAGES_PER_BATCH + 3):
            _page(conn, f"Page number {number} about a refund.", f"/docs/{number}.pdf")
        seen: list[tuple[int, int]] = []

        SemanticIndex.sync(
            storage, embedder, on_progress=lambda done, total: seen.append((done, total))
        )

        assert seen == [
            (SemanticIndex.PAGES_PER_BATCH, SemanticIndex.PAGES_PER_BATCH + 3),
            (SemanticIndex.PAGES_PER_BATCH + 3, SemanticIndex.PAGES_PER_BATCH + 3),
        ]

    def test_a_failure_keeps_the_batches_already_done(self, conn, storage, embedder, model):
        for number in range(SemanticIndex.PAGES_PER_BATCH * 2):
            _page(conn, f"Page {number} about a refund.", f"/docs/{number}.pdf")
        real = embedder.embed_passages
        calls = []

        def flaky(texts):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(texts)

        embedder.embed_passages = flaky
        with pytest.raises(RuntimeError):
            SemanticIndex.sync(storage, embedder)

        assert SemanticIndex.status(storage, model).embedded == SemanticIndex.PAGES_PER_BATCH

    def test_clear_forgets_the_embeddings(self, conn, storage, embedder, model):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)

        assert SemanticIndex.clear(storage, "someone-else") == 0
        assert SemanticIndex.status(storage, model).embedded == 1
        assert SemanticIndex.clear(storage, model) == 1
        assert SemanticIndex.status(storage, model).embedded == 0
        assert SemanticIndex.clear(storage) == 0

    def test_embedding_text_has_newlines_as_spaces(self, conn, storage, embedder):
        _page(conn, "Refund\npolicy for\ncustomers.")
        SemanticIndex.sync(storage, embedder)
        assert embedder.passages == ["Refund policy for customers."]

    def test_models_keep_separate_embeddings(self, conn, storage, embedder, model):
        _page(conn, "Refund policy.")
        SemanticIndex.sync(storage, embedder)

        class Other(type(embedder)):
            model = "other-model"

        other = Other()
        assert SemanticIndex.status(storage, other.model).embedded == 0
        SemanticIndex.sync(storage, other)
        assert SemanticIndex.status(storage, other.model).embedded == 1
        assert SemanticIndex.status(storage, model).embedded == 1
