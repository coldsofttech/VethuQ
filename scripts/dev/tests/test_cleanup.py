from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.cleanup import Cleanup


def _make_dirs(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        (root / name).mkdir()
        (root / name / "nested").mkdir()
        (root / name / "nested" / "file.txt").write_text("x")


def test_removes_every_existing_target_with_contents(tmp_path: Path) -> None:
    _make_dirs(tmp_path, Cleanup.TARGETS)

    Cleanup(root=tmp_path).run()

    assert [name for name in Cleanup.TARGETS if (tmp_path / name).exists()] == []


def test_skips_missing_targets_without_error(tmp_path: Path) -> None:
    Cleanup(root=tmp_path).run()

    assert list(tmp_path.iterdir()) == []


def test_removes_only_present_targets(tmp_path: Path) -> None:
    _make_dirs(tmp_path, (".mypy_cache", "dist"))

    Cleanup(root=tmp_path).run()

    assert not (tmp_path / ".mypy_cache").exists()
    assert not (tmp_path / "dist").exists()


def test_leaves_non_target_paths_untouched(tmp_path: Path) -> None:
    _make_dirs(tmp_path, ("build",))
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("keep")

    Cleanup(root=tmp_path).run()

    assert (tmp_path / "src").is_dir()
    assert (tmp_path / "README.md").read_text() == "keep"


def test_honours_custom_targets(tmp_path: Path) -> None:
    _make_dirs(tmp_path, ("custom", "build"))

    Cleanup(root=tmp_path, targets=("custom",)).run()

    assert not (tmp_path / "custom").exists()
    assert (tmp_path / "build").exists()


def test_reports_removed_and_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_dirs(tmp_path, ("build",))

    Cleanup(root=tmp_path, targets=("build", "dist")).run()

    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"removed {tmp_path / 'build'}",
        f"skipped {tmp_path / 'dist'} (not present)",
    ]


def test_run_is_idempotent(tmp_path: Path) -> None:
    _make_dirs(tmp_path, Cleanup.TARGETS)
    cleanup = Cleanup(root=tmp_path)

    cleanup.run()
    cleanup.run()

    assert [name for name in Cleanup.TARGETS if (tmp_path / name).exists()] == []


def test_default_root_is_repo_root() -> None:
    assert (Cleanup.REPO_ROOT / "scripts" / "dev" / "cleanup.py").is_file()
