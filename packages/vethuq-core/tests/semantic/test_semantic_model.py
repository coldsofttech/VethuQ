import sys
import types

import pytest
from vethuq_core.semantic import SemanticModel, SemanticModelError


class FakeHub(types.ModuleType):
    """A stand-in `huggingface_hub`: lists some files and "downloads" them into `local_dir`."""

    def __init__(self, files, fail=None):
        super().__init__("huggingface_hub")
        self.files = files
        self.fail = fail
        self.downloaded: list[str] = []
        outer = self

        class HfApi:
            def list_repo_files(self, repo):
                if outer.fail == "list":
                    raise OSError("no network")
                assert repo == SemanticModel.MODEL_ID
                return outer.files

        self.HfApi = HfApi

    def hf_hub_download(self, repo, filename, local_dir):
        if self.fail == filename:
            raise OSError("connection reset")
        target = local_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
        self.downloaded.append(filename)


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub(["config.json", "tokenizer.json", "onnx/model.onnx", "onnx/model_O4.onnx"])
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    return fake


class TestPickOnnxFile:
    def test_prefers_the_full_precision_export(self):
        files = ["onnx/model_quantized.onnx", "onnx/model.onnx", "tokenizer.json"]
        assert SemanticModel.pick_onnx_file(files) == "onnx/model.onnx"

    def test_then_the_quantized_one(self):
        assert (
            SemanticModel.pick_onnx_file(["onnx/model_O4.onnx", "onnx/model_quantized.onnx"])
            == "onnx/model_quantized.onnx"
        )

    def test_then_any_onnx_file(self):
        assert SemanticModel.pick_onnx_file(["onnx/b.onnx", "onnx/a.onnx"]) == "onnx/a.onnx"

    def test_none_without_an_onnx_file(self):
        assert SemanticModel.pick_onnx_file(["pytorch_model.bin", "tokenizer.json"]) is None


class TestModel:
    def test_it_is_the_multilingual_e5_small(self):
        assert SemanticModel.MODEL_ID == "intfloat/multilingual-e5-small"
        assert SemanticModel.DIMENSIONS == 384
        assert SemanticModel.cache_dir().name == "multilingual-e5-small"

    def test_not_downloaded_by_default(self):
        status = SemanticModel.status()
        assert not status.present
        assert status.size_bytes == 0
        assert SemanticModel.onnx_path() is None

    def test_download_fetches_the_tokenizer_and_the_onnx_file(self, hub):
        messages: list[str] = []

        path = SemanticModel.download(messages.append)

        assert path == SemanticModel.cache_dir() / "onnx" / "model.onnx"
        assert sorted(hub.downloaded) == ["onnx/model.onnx", "tokenizer.json"]
        assert SemanticModel.is_downloaded()
        assert SemanticModel.status().present
        assert SemanticModel.status().size_bytes > 0
        assert any("multilingual-e5-small" in m for m in messages)

    def test_a_downloaded_model_is_not_downloaded_again(self, hub):
        SemanticModel.download()
        hub.downloaded.clear()

        SemanticModel.download()

        assert hub.downloaded == []

    def test_a_failed_download_leaves_nothing_marked_as_present(self, hub):
        hub.fail = "onnx/model.onnx"

        with pytest.raises(SemanticModelError, match="Could not download"):
            SemanticModel.download()

        assert not SemanticModel.is_downloaded()

    def test_a_listing_failure_is_a_model_error(self, hub):
        hub.fail = "list"
        with pytest.raises(SemanticModelError, match="no network"):
            SemanticModel.download()

    def test_a_repository_without_onnx_is_an_error(self, hub):
        hub.files = ["tokenizer.json"]
        with pytest.raises(SemanticModelError, match="no ONNX file"):
            SemanticModel.download()

    def test_without_huggingface_hub_it_says_how_to_install_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        with pytest.raises(SemanticModelError, match=r"vethuq\[search-semantic\]"):
            SemanticModel.download()

    def test_a_marker_without_its_files_is_not_a_download(self, hub):
        SemanticModel.download()
        (SemanticModel.cache_dir() / "onnx" / "model.onnx").unlink()
        assert not SemanticModel.is_downloaded()

    def test_a_marker_for_another_model_is_not_a_download(self, hub):
        SemanticModel.download()
        (SemanticModel.cache_dir() / SemanticModel.MARKER_FILE).write_text(
            '{"model": "other/model", "onnx": "onnx/model.onnx"}', encoding="utf-8"
        )
        assert not SemanticModel.is_downloaded()

    def test_remove_deletes_the_folder(self, hub):
        SemanticModel.download()
        assert SemanticModel.remove() is True
        assert not SemanticModel.cache_dir().exists()
        assert SemanticModel.remove() is False
