"""The OCR models are not part of the image: they are downloaded once and cached, and checked.

The image build downloads the models, proves every engine loads, and records what it saw in a
lock file (`models.lock.json`: every model file's path, size and sha256), which stays in the image.
The models do not. Before a job the worker's models folder is filled by `vethuq-worker
fetch-models` (the one step that needs the network, run without the job's key or payload), and
every file is checked against the lock, both there and again when a job starts, so a cache that was
tampered with, damaged or left by another image is refused and never read.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vethuq_worker.errors import JobError


class ModelLockError(Exception):
    """The lock file can't be read, or the models don't match it."""


@dataclass(frozen=True)
class ModelLock:
    """What the models folder must hold: relative path to `(sha256, size)`."""

    VERSION = 1
    CHUNK = 1024 * 1024

    files: Mapping[str, tuple[str, int]] = field(default_factory=dict)

    # ----- making and reading ------------------------------------------------------------------

    @classmethod
    def build(cls, models: Path) -> ModelLock:
        """The lock of what `models` holds now."""
        found: dict[str, tuple[str, int]] = {}
        for path in sorted(p for p in models.rglob("*") if p.is_file() and not p.is_symlink()):
            found[path.relative_to(models).as_posix()] = (cls._digest(path), path.stat().st_size)
        if not found:
            raise ModelLockError(f"There are no models in {models} to lock.")
        return cls(found)

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.VERSION,
                "files": {
                    name: {"sha256": digest, "size": size}
                    for name, (digest, size) in sorted(self.files.items())
                },
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> ModelLock:
        try:
            data = json.loads(text)
            if data["version"] != cls.VERSION:
                raise ModelLockError(f"Models lock version {data['version']!r} isn't supported.")
            files = {
                cls._name(name): (str(item["sha256"]), int(item["size"]))
                for name, item in data["files"].items()
            }
        except ModelLockError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ModelLockError(
                f"The models lock can't be read ({type(error).__name__})."
            ) from None
        return cls(files)

    @classmethod
    def read(cls, path: Path) -> ModelLock:
        try:
            return cls.from_json(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ModelLockError(
                f"The models lock {path} can't be read: {error.strerror}."
            ) from None

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json() + "\n", encoding="utf-8")

    # ----- checking ----------------------------------------------------------------------------

    def problems(self, models: Path) -> list[str]:
        """What is wrong with `models` against this lock: nothing, when the list is empty. Files
        the lock doesn't list are ignored (another image's models may share the folder)."""
        found: list[str] = []
        for name, (digest, size) in sorted(self.files.items()):
            path = models / name
            if path.is_symlink() or not path.is_file():
                found.append(f"{name}: missing")
            elif path.stat().st_size != size:
                found.append(f"{name}: wrong size")
            elif self._digest(path) != digest:
                found.append(f"{name}: does not match the lock")
        return found

    def verify(self, models: Path) -> None:
        """Raise `ModelLockError` unless every locked file is there and matches."""
        found = self.problems(models)
        if found:
            shown = "; ".join(found[:5]) + (
                f"; and {len(found) - 5} more" if len(found) > 5 else ""
            )
            raise ModelLockError(f"The OCR models are not what this image expects ({shown}).")

    # ----- internals ---------------------------------------------------------------------------

    @staticmethod
    def _name(name: str) -> str:
        parts = Path(name).parts
        if not name or name.startswith(("/", "\\")) or ".." in parts or "\\" in name:
            raise ModelLockError(f"The models lock names an unsafe path ({name!r}).")
        return Path(*parts).as_posix()

    @classmethod
    def _digest(cls, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(cls.CHUNK):
                digest.update(chunk)
        return digest.hexdigest()


class ModelsCheck:
    """The check a job runs before it reads anything."""

    LOCK_VARIABLE = "VETHUQ_MODELS_LOCK"

    @classmethod
    def before_a_job(cls, models: Path | None, lock: Path | None) -> None:
        """Raise `JobError` if the image has a lock and the models don't match it. With no lock
        (a development install), or no models folder configured, nothing is checked."""
        if lock is None or not lock.is_file():
            return
        if models is None or not models.is_dir() or not any(models.iterdir()):
            raise JobError(
                "models_missing",
                "The OCR models have not been downloaded: run `vethuq-worker fetch-models` first.",
            )
        try:
            ModelLock.read(lock).verify(models)
        except ModelLockError as error:
            raise JobError("models_unverified", str(error)) from None


def lock_as_dict(lock: ModelLock) -> dict[str, Any]:
    """The lock as plain data (for tests and tools)."""
    return json.loads(lock.to_json())
