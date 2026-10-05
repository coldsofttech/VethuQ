import re

import pytest
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_cli.search.pager import Pager
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import open_storage

runner = CliRunner()

POLICY = "Customers may return goods within thirty days for a full reimbursement."


def _flatten(output: str) -> str:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(plain.replace("│", " ").split())


def _seed(db_path, file_path, text):
    conn = db_module.Db.connect(db_path)
    try:
        source = conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES (?, 'folder', 'indexed', '2024-01-01')",
            (file_path + ".source",),
        ).lastrowid
        logical = conn.execute("INSERT INTO documents (created_at) VALUES ('2024-01-01')").lastrowid
        document = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'pdf', 'indexed')",
            (source, logical, file_path),
        ).lastrowid
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (?, 1, ?, 0.9)",
            (document, text),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _no_pager(monkeypatch):
    monkeypatch.setattr(Pager, "page", staticmethod(lambda text, *_: print(text)))


class TestSemanticSearch:
    def test_finds_a_passage_by_meaning(self, use_temp_db, embedder):
        _seed(use_temp_db(), "/docs/policy.pdf", POLICY)
        _seed(use_temp_db(), "/docs/lunch.pdf", "Lunch is served in the cafeteria.")

        result = runner.invoke(
            app, ["search", "refund", "--engine", "semantic", "--threshold", "0.3"]
        )

        assert result.exit_code == 0, result.stdout
        flat = _flatten(result.stdout)
        assert "(engine: semantic, threshold 30%)" in flat
        assert "policy.pdf" in flat and "lunch.pdf" not in flat
        assert "full reimbursement" in flat
        assert "Related" in flat

    def test_fuzziness_names_the_semantic_presets(self, use_temp_db, embedder):
        _seed(use_temp_db(), "/docs/policy.pdf", POLICY)

        result = runner.invoke(
            app, ["search", "refund", "--engine", "semantic", "--fuzziness", "loose"]
        )

        assert result.exit_code == 0
        assert "threshold 75%" in _flatten(result.stdout)  # not fuzzy's 65%

    def test_the_threshold_defaults_to_the_setting(self, use_temp_db, embedder):
        use_temp_db()
        storage = open_storage()
        try:
            SearchSettings.set_semantic_threshold(storage, "strict")
        finally:
            storage.close()

        result = runner.invoke(app, ["search", "refund", "--engine", "semantic"])

        assert "No matches found." in result.stdout

    def test_no_matches_says_how_to_widen_it(self, use_temp_db, embedder):
        _seed(use_temp_db(), "/docs/lunch.pdf", "Lunch is served in the cafeteria.")

        result = runner.invoke(app, ["search", "refund", "--engine", "semantic"])

        assert result.exit_code == 0
        assert "No matches found." in result.stdout
        assert "semantic" in _flatten(result.stdout)

    def test_combined_with_full_text_it_shows_which_engine_found_each_hit(
        self, use_temp_db, embedder
    ):
        db_path = use_temp_db()
        _seed(db_path, "/docs/both.pdf", "Refund and reimbursement of the repayment.")
        storage = open_storage()
        try:
            SearchSettings.set_semantic_combine(storage, "full-text")
        finally:
            storage.close()

        result = runner.invoke(
            app, ["search", "refund", "--engine", "semantic", "--threshold", "0.2"]
        )

        flat = _flatten(result.stdout)
        assert result.exit_code == 0
        assert "Related" in flat and "Word" in flat

    def test_case_sensitive_is_refused(self, use_temp_db, embedder):
        use_temp_db()
        result = runner.invoke(app, ["search", "x", "--engine", "semantic", "--case-sensitive"])
        assert result.exit_code != 0
        assert "case-insensitive" in _flatten(result.output)

    @pytest.mark.parametrize(
        "args", [["--distance", "3"], ["--noise", "low"], ["--leet-level", "basic"]]
    )
    def test_options_of_other_engines_are_refused(self, use_temp_db, embedder, args):
        use_temp_db()
        result = runner.invoke(app, ["search", "x", "--engine", "semantic", *args])
        assert result.exit_code != 0

    def test_a_model_that_cannot_load_is_reported_not_a_traceback(self, use_temp_db):
        from vethuq_core.semantic import Embedders, SemanticModelError

        _seed(use_temp_db(), "/docs/policy.pdf", POLICY)

        def refuse():
            raise SemanticModelError("The model is not downloaded")

        Embedders.use(refuse)
        try:
            result = runner.invoke(app, ["search", "refund", "--engine", "semantic"])
        finally:
            Embedders.use(None)

        assert result.exit_code == 1
        assert "not downloaded" in _flatten(result.output)

    def test_the_help_describes_the_engine(self):
        result = runner.invoke(app, ["search", "--help"])
        flat = _flatten(result.stdout)
        assert "semantic" in flat and "multilingual-e5-small" in flat
