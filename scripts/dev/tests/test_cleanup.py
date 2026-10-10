from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.cleanup import Cleanup


class TestCleanup:
    @staticmethod
    def _make_dirs(root: Path, names: tuple[str, ...]) -> None:
        for name in names:
            (root / name).mkdir()
            (root / name / "nested").mkdir()
            (root / name / "nested" / "file.txt").write_text("x")

    @staticmethod
    def _existing(root: Path) -> list[str]:
        return [name for name in Cleanup.TARGETS if (root / name).exists()]

    def test_removes_every_existing_target_with_contents(self, tmp_path: Path) -> None:
        self._make_dirs(tmp_path, Cleanup.TARGETS)

        Cleanup(root=tmp_path).run()

        assert self._existing(tmp_path) == []

    def test_skips_missing_targets_without_error(self, tmp_path: Path) -> None:
        Cleanup(root=tmp_path).run()

        assert list(tmp_path.iterdir()) == []

    def test_removes_only_present_targets(self, tmp_path: Path) -> None:
        self._make_dirs(tmp_path, (".mypy_cache", "dist"))

        Cleanup(root=tmp_path).run()

        assert not (tmp_path / ".mypy_cache").exists()
        assert not (tmp_path / "dist").exists()

    def test_leaves_non_target_paths_untouched(self, tmp_path: Path) -> None:
        self._make_dirs(tmp_path, ("build",))
        (tmp_path / "src").mkdir()
        (tmp_path / "README.md").write_text("keep")

        Cleanup(root=tmp_path).run()

        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "README.md").read_text() == "keep"

    def test_honours_custom_targets(self, tmp_path: Path) -> None:
        self._make_dirs(tmp_path, ("custom", "build"))

        Cleanup(root=tmp_path, targets=("custom",)).run()

        assert not (tmp_path / "custom").exists()
        assert (tmp_path / "build").exists()

    def test_reports_removed_and_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._make_dirs(tmp_path, ("build",))

        Cleanup(root=tmp_path, targets=("build", "dist")).run()

        out = capsys.readouterr().out.splitlines()
        assert out == [
            f"removed {tmp_path / 'build'}",
            f"skipped {tmp_path / 'dist'} (not present)",
        ]

    def test_run_is_idempotent(self, tmp_path: Path) -> None:
        self._make_dirs(tmp_path, Cleanup.TARGETS)
        cleanup = Cleanup(root=tmp_path)

        cleanup.run()
        cleanup.run()

        assert self._existing(tmp_path) == []

    def test_default_root_is_repo_root(self) -> None:
        assert (Cleanup.REPO_ROOT / "scripts" / "dev" / "cleanup.py").is_file()
