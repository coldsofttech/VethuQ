"""The embedding model behind semantic search: where it lives, and fetching it.

VethuQ uses `intfloat/multilingual-e5-small` (ONNX): a small model that reads about a hundred
languages, Telugu and English among them, into one space, so a Telugu query finds the English
page that says the same thing. It is not part of the installer - like the OCR models it is
downloaded the first time semantic search needs it, into `<data root>/models/semantic/`, or
earlier with `vethuq semantic download`. The download needs `huggingface_hub`, which the
`search-semantic` extra installs.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vethuq_core.hints import Hints
from vethuq_core.logs import Logs
from vethuq_core.paths import Paths

_logger = Logs.get_logger("index")


class SemanticModelError(Exception):
    """The embedding model can't be downloaded or loaded; the message says why."""


@dataclass(frozen=True)
class SemanticModelStatus:
    """The model's id, folder and whether it is downloaded (and how big it is on disk)."""

    model: str
    path: Path
    present: bool
    size_bytes: int


class SemanticModel:
    # The Hugging Face repository the model comes from; it is also the name embeddings are
    # recorded under, so changing it means every page is embedded again.
    MODEL_ID = "intfloat/multilingual-e5-small"
    # The size of the vectors the model produces.
    DIMENSIONS = 384
    # The most tokens the model reads in one go; longer text is cut off.
    MAX_TOKENS = 512
    # E5 models are trained with these prefixes on the text they compare, and score noticeably
    # worse without them.
    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    TOKENIZER_FILE = "tokenizer.json"
    MARKER_FILE = "vethuq-model.json"
    # The ONNX files to take from the repository, best first: the full-precision export, then
    # the quantized one. Any other `onnx/*.onnx` is used if neither exists.
    ONNX_PREFERENCE = ("onnx/model.onnx", "onnx/model_quantized.onnx")

    @staticmethod
    def folder_name() -> str:
        return SemanticModel.MODEL_ID.rsplit("/", 1)[-1]

    @staticmethod
    def cache_dir() -> Path:
        """The folder the model is kept in."""
        return Paths.default_data_root() / "models" / "semantic" / SemanticModel.folder_name()

    @staticmethod
    def _marker() -> dict[str, Any] | None:
        try:
            data = json.loads(
                (SemanticModel.cache_dir() / SemanticModel.MARKER_FILE).read_text("utf-8")
            )
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def onnx_path() -> Path | None:
        """The downloaded ONNX file, or None if the model is not (completely) downloaded."""
        marker = SemanticModel._marker()
        if marker is None or marker.get("model") != SemanticModel.MODEL_ID:
            return None
        onnx = SemanticModel.cache_dir() / str(marker.get("onnx", ""))
        tokenizer = SemanticModel.cache_dir() / SemanticModel.TOKENIZER_FILE
        return onnx if onnx.is_file() and tokenizer.is_file() else None

    @staticmethod
    def is_downloaded() -> bool:
        return SemanticModel.onnx_path() is not None

    @staticmethod
    def pick_onnx_file(files: list[str]) -> str | None:
        """The file to download from the repository's `files`, or None if it has no ONNX file."""
        for preferred in SemanticModel.ONNX_PREFERENCE:
            if preferred in files:
                return preferred
        others = sorted(f for f in files if f.startswith("onnx/") and f.endswith(".onnx"))
        return others[0] if others else None

    @staticmethod
    def _size(folder: Path) -> int:
        return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())

    @staticmethod
    def status() -> SemanticModelStatus:
        folder = SemanticModel.cache_dir()
        present = SemanticModel.is_downloaded()
        return SemanticModelStatus(
            model=SemanticModel.MODEL_ID,
            path=folder,
            present=present,
            size_bytes=SemanticModel._size(folder) if folder.is_dir() else 0,
        )

    @staticmethod
    def download(on_progress: Callable[[str], None] | None = None) -> Path:
        """Download the model if it is not there yet; returns its ONNX file.

        Raises `SemanticModelError` if `huggingface_hub` is missing or the download fails
        (no network, the repository unreachable); nothing half-downloaded is left marked as
        present.
        """
        existing = SemanticModel.onnx_path()
        if existing is not None:
            return existing
        try:
            from huggingface_hub import HfApi, hf_hub_download
        except ImportError as exc:
            raise SemanticModelError(
                "Semantic search needs huggingface_hub to download its model. "
                "Install it with: pip install vethuq[search-semantic]"
            ) from exc

        folder = SemanticModel.cache_dir()
        say = on_progress or (lambda _: None)
        try:
            say(f"Downloading {SemanticModel.MODEL_ID}")
            files = list(HfApi().list_repo_files(SemanticModel.MODEL_ID))
            onnx = SemanticModel.pick_onnx_file(files)
            if onnx is None:
                raise SemanticModelError(f"{SemanticModel.MODEL_ID} has no ONNX file to download.")
            folder.mkdir(parents=True, exist_ok=True)
            marker = folder / SemanticModel.MARKER_FILE
            marker.unlink(missing_ok=True)
            for name in (SemanticModel.TOKENIZER_FILE, onnx):
                say(f"  {name}")
                hf_hub_download(SemanticModel.MODEL_ID, name, local_dir=folder)
            marker.write_text(
                json.dumps({"model": SemanticModel.MODEL_ID, "onnx": onnx}), encoding="utf-8"
            )
        except SemanticModelError:
            raise
        except Exception as exc:  # noqa: BLE001 - any network/hoster failure is reported, not raised
            _logger.error("Downloading the semantic model failed: %s: %s", type(exc).__name__, exc)
            raise SemanticModelError(
                f"Could not download the semantic search model ({exc}). "
                f"Check the connection and try again with: {Hints.command('semantic download')}"
            ) from exc
        path = SemanticModel.onnx_path()
        if path is None:  # pragma: no cover - the files were just written
            raise SemanticModelError("The semantic search model did not download completely.")
        _logger.info("Downloaded the semantic model %s", SemanticModel.MODEL_ID)
        return path

    @staticmethod
    def remove() -> bool:
        """Delete the downloaded model. Returns whether there was anything to delete."""
        folder = SemanticModel.cache_dir()
        if not folder.exists():
            return False
        shutil.rmtree(folder, ignore_errors=True)
        return True
