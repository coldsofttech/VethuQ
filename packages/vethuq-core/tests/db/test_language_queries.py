import pytest
from vethuq_core.db.queries.ocr import Ocr


def _seed(conn):
    conn.executescript(
        """
        INSERT INTO sources (id, path, source_type, status, added_at)
            VALUES (1, '/a', 'folder', 'indexed', '2024-01-01'),
                   (2, '/b', 'folder', 'indexed', '2024-01-01');
        INSERT INTO documents (created_at) VALUES ('2024-01-01'), ('2024-01-01'), ('2024-01-01');
        INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
            VALUES (1, 1, 1, '/a/x.pdf', 'pdf', 'indexed'),
                   (2, 1, 2, '/a/y.png', 'image', 'indexed'),
                   (3, 2, 3, '/b/z.png', 'image', 'indexed');
        """
    )


@pytest.fixture
def db(conn):
    _seed(conn)
    return conn


ROWS = [("en", 0, "done", "auto", 0.4), ("te", 1, "pending", "auto", None)]


class TestReplaceAndGet:
    def test_replace_sets_a_files_passes_in_order(self, db):
        Ocr.Language.replace(db, 1, ROWS)

        rows = Ocr.Language.get(db, 1)

        assert [(r["language"], r["position"], r["status"], r["source"]) for r in rows] == [
            ("en", 0, "done", "auto"),
            ("te", 1, "pending", "auto"),
        ]
        assert rows[0]["confidence"] == 0.4 and rows[1]["confidence"] is None

    def test_replace_discards_the_earlier_passes(self, db):
        Ocr.Language.replace(db, 1, ROWS)

        Ocr.Language.replace(db, 1, [("en", 0, "done", "manual", 0.9)])

        assert [r["language"] for r in Ocr.Language.get(db, 1)] == ["en"]

    def test_files_are_independent(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.replace(db, 2, [("te", 0, "done", "manual", None)])

        assert len(Ocr.Language.get(db, 1)) == 2
        assert len(Ocr.Language.get(db, 2)) == 1
        assert Ocr.Language.get(db, 3) == []


class TestUpdate:
    def test_records_status_timing_and_confidence(self, db):
        Ocr.Language.replace(db, 1, ROWS)

        Ocr.Language.update(db, 1, "te", "done", 0.8, None, "t0", "t1")

        row = Ocr.Language.get(db, 1)[1]
        assert (row["status"], row["confidence"], row["started_at"], row["completed_at"]) == (
            "done",
            0.8,
            "t0",
            "t1",
        )

    def test_an_error_keeps_its_message(self, db):
        Ocr.Language.replace(db, 1, ROWS)

        Ocr.Language.update(db, 1, "te", "error", None, "boom", None, "t1")

        row = Ocr.Language.get(db, 1)[1]
        assert (row["status"], row["error_message"]) == ("error", "boom")

    def test_no_new_confidence_or_start_keeps_the_earlier_ones(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.update(db, 1, "te", "processing", None, None, "t0", None)

        Ocr.Language.update(db, 1, "te", "done", 0.7, None, None, "t1")
        row = Ocr.Language.get(db, 1)[1]

        assert row["started_at"] == "t0" and row["confidence"] == 0.7


class TestListPending:
    def test_lists_the_pending_passes_of_indexed_files(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.replace(db, 2, ROWS)

        rows = Ocr.Language.list_pending(db, [1])

        assert [(r["document_id"], r["language"], r["file_type"]) for r in rows] == [
            (1, "te", "pdf"),
            (2, "te", "image"),
        ]
        assert rows[0]["file_path"] == "/a/x.pdf"
        assert rows[0]["choice_source"] == "auto"

    def test_only_the_sources_asked_for(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.replace(db, 3, ROWS)

        assert [r["document_id"] for r in Ocr.Language.list_pending(db, [2])] == [3]
        assert Ocr.Language.list_pending(db, []) == []

    def test_a_pass_waits_for_the_ones_before_it(self, db):
        Ocr.Language.replace(
            db,
            1,
            [
                ("en", 0, "done", "auto", None),
                ("te", 1, "pending", "auto", None),
                ("xx", 2, "pending", "auto", None),
            ],
        )

        assert [r["language"] for r in Ocr.Language.list_pending(db, [1])] == ["te"]
        Ocr.Language.update(db, 1, "te", "processing", None, None, "t", None)
        assert Ocr.Language.list_pending(db, [1]) == []
        Ocr.Language.update(db, 1, "te", "done", None, None, None, "t")
        assert [r["language"] for r in Ocr.Language.list_pending(db, [1])] == ["xx"]

    def test_a_failed_pass_does_not_hold_up_the_next(self, db):
        Ocr.Language.replace(
            db,
            1,
            [("te", 1, "error", "auto", None), ("xx", 2, "pending", "auto", None)],
        )

        assert [r["language"] for r in Ocr.Language.list_pending(db, [1])] == ["xx"]

    def test_earlier_positions_come_first_across_files(self, db):
        Ocr.Language.replace(
            db, 1, [("en", 0, "done", "auto", None), ("xx", 2, "pending", "auto", None)]
        )
        Ocr.Language.replace(db, 2, [("te", 1, "pending", "auto", None)])

        assert [(r["document_id"], r["position"]) for r in Ocr.Language.list_pending(db, [1])] == [
            (2, 1),
            (1, 2),
        ]

    def test_files_that_are_not_indexed_or_are_being_reindexed_are_left_out(self, db):
        for document_id in (1, 2, 3):
            Ocr.Language.replace(db, document_id, ROWS)
        db.execute("UPDATE document_index SET status = 'error' WHERE id = 1")
        db.execute("UPDATE document_index SET reindex_pending = 1 WHERE id = 2")

        assert [r["document_id"] for r in Ocr.Language.list_pending(db, [1, 2])] == [3]

    def test_done_and_skipped_passes_are_not_pending(self, db):
        Ocr.Language.replace(
            db, 1, [("en", 0, "done", "auto", None), ("te", 1, "skipped", "auto", None)]
        )

        assert Ocr.Language.list_pending(db, [1]) == []
        assert Ocr.Language.count_pending(db, [1]) == 0

    def test_count(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.replace(db, 2, ROWS)

        assert Ocr.Language.count_pending(db, [1]) == 2


class TestResetProcessing:
    def test_puts_interrupted_passes_back_in_the_queue(self, db):
        Ocr.Language.replace(db, 1, ROWS)
        Ocr.Language.update(db, 1, "te", "processing", None, None, "t", None)

        assert Ocr.Language.reset_processing(db) == 1

        row = Ocr.Language.get(db, 1)[1]
        assert row["status"] == "pending" and row["started_at"] is None

    def test_leaves_the_rest_alone(self, db):
        Ocr.Language.replace(db, 1, ROWS)

        assert Ocr.Language.reset_processing(db) == 0


class TestPages:
    def test_pdf_pages_come_in_page_order(self, db):
        db.executemany(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source, "
            "language) VALUES (1, ?, ?, 0.9, ?, 'en')",
            [(2, "two", "ocr"), (1, "one", "native")],
        )

        rows = Ocr.Language.list_pages(db, "pdf_pages", 1)

        assert [(r["page_number"], r["ocr_text"], r["source"]) for r in rows] == [
            (1, "one", "native"),
            (2, "two", "ocr"),
        ]

    def test_an_image_has_one_scanned_page(self, db):
        db.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence, language) "
            "VALUES (2, 'hi', 0.9, 'en')"
        )

        [row] = Ocr.Language.list_pages(db, "image_pages", 2)

        assert (row["page_number"], row["source"], row["language"], row["ocr_langs"]) == (
            1,
            "ocr",
            "en",
            "",
        )

    @pytest.mark.parametrize(
        "table, insert",
        [
            (
                "pdf_pages",
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (1, 1, 'x', 0.9)",
            ),
            (
                "image_pages",
                "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (2, 'x', 0.9)",
            ),
        ],
    )
    def test_updating_a_pages_languages(self, db, table, insert):
        page_id = db.execute(insert).lastrowid

        Ocr.Language.update_page_languages(db, table, page_id, "te", "en,te")

        row = db.execute(f"SELECT language, ocr_langs FROM {table}").fetchone()
        assert (row["language"], row["ocr_langs"]) == ("te", "en,te")
