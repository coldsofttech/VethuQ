import importlib.machinery
import sys
import types

import pytest
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.semantic import SemanticIndex, SemanticModel
from vethuq_core.storage import open_storage

runner = CliRunner()


def _seed(db_path, text="Customers may return goods for a full reimbursement.", path="/d/a.pdf"):
    import vethuq_core.db as db_module

    conn = db_module.Db.connect(db_path)
    try:
        source = conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES (?, 'folder', 'indexed', '2024-01-01')",
            (path + ".src",),
        ).lastrowid
        logical = conn.execute("INSERT INTO documents (created_at) VALUES ('2024-01-01')").lastrowid
        document = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'pdf', 'indexed')",
            (source, logical, path),
        ).lastrowid
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (?, 1, ?, 0.9)",
            (document, text),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def hub(monkeypatch):
    fake = types.ModuleType("huggingface_hub")
    # `importlib.util.find_spec` (which the engine catalog uses) refuses a module without one.
    fake.__spec__ = importlib.machinery.ModuleSpec("huggingface_hub", None)

    class HfApi:
        def list_repo_files(self, repo):
            return ["tokenizer.json", "onnx/model.onnx"]

    def hf_hub_download(repo, filename, local_dir):
        target = local_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")

    fake.HfApi = HfApi
    fake.hf_hub_download = hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)


class TestStatus:
    def test_before_anything_is_downloaded_or_embedded(self, use_temp_db):
        _seed(use_temp_db())

        result = runner.invoke(app, ["semantic", "status"])

        assert result.exit_code == 0
        assert "multilingual-e5-small" in result.stdout
        assert "downloads the first time it is used" in result.stdout.replace("\n", " ")
        assert "0 of 1" in result.stdout

    def test_after_download_and_index(self, use_temp_db, embedder, hub):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "download"])
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "status"])

        assert "yes (" in result.stdout
        assert "1 of 1" in result.stdout


class TestStatusStore:
    def test_shows_the_separate_store_and_the_embedding_version(self, use_temp_db, embedder):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "status"])

        flat = " ".join(result.stdout.split())
        assert "vethuq.semantic.db" in flat.replace("│", "").replace(" ", "")
        assert "Embedding version" in flat
        assert "Out of date" not in flat

    def test_says_when_pages_were_embedded_another_way(self, use_temp_db, embedder, monkeypatch):
        from vethuq_core.semantic import SemanticIndex

        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])
        monkeypatch.setattr(SemanticIndex, "VERSION", SemanticIndex.VERSION + 1)

        result = runner.invoke(app, ["semantic", "status"])

        assert "Out of date" in result.stdout
        assert "0 of 1" in result.stdout


class TestDownload:
    def test_downloads_the_model(self, use_temp_db, hub):
        use_temp_db()

        result = runner.invoke(app, ["semantic", "download"])

        assert result.exit_code == 0, result.stdout
        assert SemanticModel.is_downloaded()
        assert "Downloaded intfloat/multilingual-e5-small" in result.stdout.replace("\n", " ")

    def test_a_second_download_does_nothing(self, use_temp_db, hub):
        use_temp_db()
        runner.invoke(app, ["semantic", "download"])

        result = runner.invoke(app, ["semantic", "download"])

        assert result.exit_code == 0
        assert "already downloaded" in result.stdout

    def test_force_downloads_again(self, use_temp_db, hub):
        use_temp_db()
        runner.invoke(app, ["semantic", "download"])
        result = runner.invoke(app, ["semantic", "download", "--force"])
        assert result.exit_code == 0 and "Downloaded" in result.stdout

    def test_a_failure_says_what_to_do(self, use_temp_db, monkeypatch):
        use_temp_db()
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)

        result = runner.invoke(app, ["semantic", "download"])

        assert result.exit_code == 1


class TestIndex:
    def test_embeds_the_pages_that_are_missing(self, use_temp_db, embedder):
        db_path = use_temp_db()
        _seed(db_path, path="/d/a.pdf")
        _seed(db_path, "The museum opens at nine.", path="/d/b.pdf")

        result = runner.invoke(app, ["semantic", "index"])

        assert result.exit_code == 0, result.stdout
        assert "Embedded 2 pages (2 passages)" in result.stdout.replace("\n", " ")

    def test_a_second_run_has_nothing_to_do(self, use_temp_db, embedder):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "index"])

        assert "Every page is already embedded" in result.stdout

    def test_rebuild_embeds_everything_again(self, use_temp_db, embedder):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "index", "--rebuild"])

        assert "Embedded 1 pages" in result.stdout.replace("\n", " ")

    def test_a_model_that_cannot_load_is_reported(self, use_temp_db):
        from vethuq_core.semantic import Embedders, SemanticModelError

        _seed(use_temp_db())

        def refuse():
            raise SemanticModelError("offline")

        Embedders.use(refuse)
        try:
            result = runner.invoke(app, ["semantic", "index"])
        finally:
            Embedders.use(None)

        assert result.exit_code == 1
        assert "offline" in result.output


class TestClear:
    def test_forgets_the_embeddings(self, use_temp_db, embedder):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "clear", "--force"])

        assert result.exit_code == 0
        assert "Forgot the embeddings of 1 pages" in result.stdout.replace("\n", " ")
        storage = open_storage()
        try:
            assert (
                storage.count_semantic(SemanticModel.MODEL_ID, SemanticIndex.version())["embedded"]
                == 0
            )
        finally:
            storage.close()

    def test_model_flag_also_deletes_the_model(self, use_temp_db, hub):
        use_temp_db()
        runner.invoke(app, ["semantic", "download"])

        result = runner.invoke(app, ["semantic", "clear", "--model", "--force"])

        assert result.exit_code == 0
        assert not SemanticModel.is_downloaded()

    def test_asks_before_deleting(self, use_temp_db, embedder):
        _seed(use_temp_db())
        runner.invoke(app, ["semantic", "index"])

        result = runner.invoke(app, ["semantic", "clear"], input="n\n")

        assert "Aborted" in result.stdout
