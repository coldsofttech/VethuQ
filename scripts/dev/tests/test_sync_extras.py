from __future__ import annotations

from scripts.dev.sync_extras import SyncExtras


def test_repo_default_addons_are_in_step():
    assert SyncExtras().in_step()


def test_ids_skip_the_api_and_write_is_idempotent(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    deps = '"psutil>=5", "vethuq-addon-api~=0.1", "vethuq-addon-pdf~=0.1"'
    pyproject.write_text(f"[project]\ndependencies = [{deps}]\n")
    sync = SyncExtras(pyproject, tmp_path / "out.txt")
    assert sync.ids() == ["pdf"]
    assert sync.write() is True and sync.write() is False
    assert sync.in_step()
