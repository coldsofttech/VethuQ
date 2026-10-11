from __future__ import annotations

import json
import stat
import sys

import pytest
import yaml

import vethuq
from tests.fake_github import FakeGitHub
from vethuq import errors
from vethuq._github import _Caller, _Compatibility, _MasterKey
from vethuq.github import GitHub, GitHubRunner, GitHubStatus, GitHubVersion

WORKFLOW = ".github/workflows/vethuq-ocr.yml"


@pytest.fixture
def fake():
    return FakeGitHub()


@pytest.fixture
def client(tmp_path, fake):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client._github_transport = fake
        yield client


class TestTemplate:
    def test_the_caller_is_valid_yaml_with_one_trigger(self):
        row = _Compatibility.choose("0.1.0")
        data = yaml.safe_load(_Caller.render(row))
        assert list(data[True]) == ["workflow_dispatch"]  # YAML reads `on` as True
        inputs = data[True]["workflow_dispatch"]["inputs"]
        assert sorted(inputs) == ["asset", "job_id"]
        assert data["permissions"] == {"contents": "read"}
        job = data["jobs"]["ocr"]
        assert job["uses"].endswith(f"github-ocr.yml@{row.workflow_ref}")
        assert job["with"]["image"] == row.image
        assert job["secrets"] == {"master_key": "${{ secrets.VETHUQ_MASTER_KEY }}"}

    def test_the_pin_and_image_are_on_single_parseable_lines(self):
        row = _Compatibility.choose("0.1.0")
        text = _Caller.render(row)
        assert _Caller.pin(text) == row.workflow_ref and _Caller.image(text) == row.image
        assert "__" not in text
        assert _Caller.pin("name: other\n") is None

    def test_the_reusable_workflow_matches_what_the_caller_calls(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "github-ocr.yml"
        data = yaml.safe_load(path.read_text())
        call = data[True]["workflow_call"]
        assert sorted(call["inputs"]) == ["asset", "image", "job_id"]
        assert list(call["secrets"]) == ["master_key"]
        row = _Compatibility.choose("0.1.0")
        caller = yaml.safe_load(_Caller.render(row))["jobs"]["ocr"]
        assert sorted(caller["with"]) == sorted(call["inputs"])

    def test_the_table(self):
        rows = _Compatibility.rows()
        assert [r.workflow_ref for r in rows] == ["github-tier-v0.1.0"]
        assert rows[0].image.startswith("ghcr.io/coldsofttech/vethuq-worker")
        assert _Compatibility.choose("0.1.0").status == "provisional"

    def test_a_client_too_old_for_every_row(self):
        with pytest.raises(errors.GitHubSetupError, match="No runner version"):
            _Compatibility.choose("0.0.1")

    def test_only_listed_versions_can_be_chosen(self):
        with pytest.raises(errors.GitHubSetupError, match="isn't a runner version"):
            _Compatibility.choose("1.0.0", "main")

    def test_a_withdrawn_row_is_never_chosen(self, monkeypatch):
        from vethuq._github import template

        rows = [
            template._Row("a", "ghcr.io/coldsofttech/vethuq-worker:a", 1, "0.1.0", "released"),
            template._Row("b", "ghcr.io/coldsofttech/vethuq-worker:b", 1, "0.1.0", "withdrawn"),
        ]
        monkeypatch.setattr(template._Compatibility, "rows", staticmethod(lambda: rows))
        assert template._Compatibility.choose("1.0.0").workflow_ref == "a"
        with pytest.raises(errors.GitHubSetupError):
            template._Compatibility.choose("1.0.0", "b")


class TestSetup:
    def test_it_creates_a_private_repository_with_the_caller_and_the_key(self, client, fake):
        runner = client.github.setup("my-runner", token="ghp_good")
        assert isinstance(client.github, GitHub) and isinstance(runner, GitHubRunner)
        assert (runner.full_name, runner.private, runner.protocol) == ("octo/my-runner", True, 1)
        assert runner.url == "https://github.com/octo/my-runner"
        repo = fake.repo("octo/my-runner")
        assert (
            repo["private"] is True and repo["has_issues" if False else "default_branch"] == "main"
        )
        text, _ = repo["files"][WORKFLOW]
        assert _Caller.pin(text) == runner.workflow_ref and _Caller.image(text) == runner.image
        assert "set up by VethuQ" in repo["files"]["README.md"][0]
        assert repo["workflow_permissions"] == "read"

    def test_the_key_is_kept_locally_and_given_to_the_repository(self, client, fake):
        runner = client.github.setup("r", token="ghp_good")
        from vethuq._paths import _Paths

        path = _Paths.github_dir(client.db_path, create=False) / "master.key"
        local = path.read_text().strip()
        assert fake.secret_value("octo/r", "VETHUQ_MASTER_KEY") == local
        assert len(_MasterKey.decode(local)) == 32
        assert runner.key_fingerprint == _MasterKey.fingerprint(local)
        if sys.platform != "win32":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_the_token_is_never_stored_or_shown(self, client, fake, tmp_path):
        runner = client.github.setup("r", token="ghp_good")
        assert fake.tokens_seen == {"Bearer ghp_good"}
        everything = runner.to_json() + client.github.status("ghp_good").to_json()
        assert "ghp_good" not in everything
        for path in (tmp_path / "db").rglob("*"):
            if path.is_file():
                assert b"ghp_good" not in path.read_bytes()

    def test_the_token_can_come_from_the_environment(self, client, fake, monkeypatch):
        monkeypatch.setenv("VETHUQ_GITHUB_TOKEN", "ghp_good")
        assert client.github.setup("r").full_name == "octo/r"
        monkeypatch.delenv("VETHUQ_GITHUB_TOKEN")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_good")
        assert client.github.setup("r2").full_name == "octo/r2"

    def test_no_token_is_refused(self, client, monkeypatch):
        monkeypatch.delenv("VETHUQ_GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(errors.GitHubAuthError, match="No GitHub token"):
            client.github.setup("r")

    def test_a_rejected_token(self, client):
        with pytest.raises(errors.GitHubAuthError, match="rejected"):
            client.github.setup("r", token="nope")
        assert client.github.runner() is None

    def test_a_token_that_is_too_weak(self, client, fake):
        fake.forbidden = ["/contents/"]
        with pytest.raises(errors.GitHubAuthError, match="isn't allowed"):
            client.github.setup("r", token="ghp_good")
        assert client.github.runner() is None  # nothing is remembered when it didn't finish

    def test_an_organization(self, client, fake):
        runner = client.github.setup("r", owner="acme", token="ghp_good")
        assert runner.full_name == "acme/r" and ("POST", "/orgs/acme/repos") in fake.calls
        with pytest.raises(errors.GitHubSetupError):
            client.github.setup("r", owner="nobody", token="ghp_good")

    def test_a_public_repository_if_asked(self, client, fake):
        runner = client.github.setup("r", private=False, token="ghp_good")
        assert runner.private is False and fake.repo("octo/r")["private"] is False
        assert any("public" in p for p in client.github.status("ghp_good").problems)

    @pytest.mark.parametrize("name", ["", "has space", "a/b", "..", ".", "x" * 101])
    def test_bad_names(self, client, name):
        with pytest.raises(errors.GitHubSetupError, match="valid repository"):
            client.github.setup(name, token="ghp_good")

    @pytest.mark.parametrize("owner", ["-bad", "a b", "x" * 40, "a/b"])
    def test_bad_owners(self, client, owner):
        with pytest.raises(errors.GitHubSetupError, match="valid GitHub user"):
            client.github.setup("r", owner=owner, token="ghp_good")

    def test_running_it_again_repairs_and_changes_nothing_else(self, client, fake):
        first = client.github.setup("r", token="ghp_good")
        commits = len(fake.repo("octo/r")["commits"])
        key = fake.secret_value("octo/r", "VETHUQ_MASTER_KEY")
        again = client.github.setup("r", token="ghp_good")
        assert again.key_fingerprint == first.key_fingerprint
        assert len(fake.repo("octo/r")["commits"]) == commits  # the workflow was already right
        assert fake.secret_value("octo/r", "VETHUQ_MASTER_KEY") == key

    def test_a_deleted_workflow_comes_back(self, client, fake):
        client.github.setup("r", token="ghp_good")
        del fake.repo("octo/r")["files"][WORKFLOW]
        client.github.setup("r", token="ghp_good")
        assert WORKFLOW in fake.repo("octo/r")["files"]

    def test_a_repository_that_is_not_ours_is_refused(self, client, fake):
        fake.create("octo", {"name": "mine", "private": True, "auto_init": True})
        with pytest.raises(errors.GitHubSetupError, match="wasn't set up by VethuQ"):
            client.github.setup("mine", token="ghp_good")
        assert client.github.runner() is None

    def test_adopting_an_existing_repository(self, client, fake):
        fake.create("octo", {"name": "mine", "private": True, "auto_init": True})
        runner = client.github.setup("mine", token="ghp_good", adopt=True)
        assert WORKFLOW in fake.repo("octo/mine")["files"] and runner.repo == "mine"
        assert fake.repo("octo/mine")["files"]["README.md"][0] == "# new\n"  # its own README

    def test_create_false_needs_the_repository(self, client, fake):
        with pytest.raises(errors.GitHubSetupError, match="doesn't exist"):
            client.github.setup("r", token="ghp_good", create=False)

    def test_an_existing_key_can_be_restored(self, client, fake):
        key = _MasterKey.encode(b"k" * 32)
        runner = client.github.setup("r", token="ghp_good", master_key=key)
        assert fake.secret_value("octo/r", "VETHUQ_MASTER_KEY") == key
        assert runner.key_fingerprint == _MasterKey.fingerprint(key)
        other = client.github.setup("r", token="ghp_good", master_key=b"z" * 32)
        assert other.key_fingerprint != runner.key_fingerprint

    @pytest.mark.parametrize("key", ["short", "!!!!", b"short", "A" * 10])
    def test_a_bad_key(self, client, key):
        with pytest.raises(errors.GitHubSetupError, match="256-bit"):
            client.github.setup("r", token="ghp_good", master_key=key)

    def test_a_network_failure(self, client):
        def down(*args):
            raise ConnectionError("offline")

        client._github_transport = down
        client._github = None
        with pytest.raises(errors.GitHubSetupError, match="reach GitHub"):
            client.github.setup("r", token="ghp_good")

    def test_other_http_errors(self, client, fake):
        fake.fail = {"/user": 500}
        with pytest.raises(errors.GitHubSetupError, match="500"):
            client.github.setup("r", token="ghp_good")
        fake.fail = {"/user": 429}
        with pytest.raises(errors.GitHubError, match="rate limiting"):
            client.github.setup("r", token="ghp_good")

    def test_the_policy_can_switch_the_tier_off(self, client, fake):
        updates = client.updates
        updates.feature = lambda name, default: type(
            "F", (), {"allowed": False, "message": "GitHub tier is paused."}
        )()
        client._github = None
        with pytest.raises(errors.GitHubUnavailableError, match="paused"):
            client.github.setup("r", token="ghp_good")
        assert fake.calls == []  # it did not even ask GitHub

    def test_a_workflow_tag_outside_the_table_is_refused(self, client, fake):
        with pytest.raises(errors.GitHubSetupError):
            client.github.setup("r", token="ghp_good", workflow_ref="main")
        assert fake.calls == []

    def test_the_choice_is_remembered_across_clients(self, client, tmp_path, fake):
        client.github.setup("r", token="ghp_good")
        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.github.runner().full_name == "octo/r"


class TestStatus:
    def test_a_healthy_runner(self, client, fake):
        client.github.setup("r", token="ghp_good")
        status = client.github.status("ghp_good")
        assert isinstance(status, GitHubStatus)
        assert (status.ok, status.caller_ok, status.secret_set, status.up_to_date) == (
            True,
            True,
            True,
            True,
        )
        assert status.private is True and status.problems == []
        assert json.loads(status.to_json()) == status.to_dict()

    def test_no_runner(self, client):
        with pytest.raises(errors.GitHubNotSetUpError):
            client.github.status("ghp_good")
        assert client.github.runner() is None

    def test_a_changed_workflow_is_found(self, client, fake):
        client.github.setup("r", token="ghp_good")
        text, sha = fake.repo("octo/r")["files"][WORKFLOW]
        fake.repo("octo/r")["files"][WORKFLOW] = (text + "# edited\n", sha)
        status = client.github.status("ghp_good")
        assert not status.caller_ok and not status.ok
        assert "The runner workflow was changed." in status.problems

    def test_a_foreign_workflow(self, client, fake):
        client.github.setup("r", token="ghp_good")
        fake.repo("octo/r")["files"][WORKFLOW] = ("name: other\n", "x")
        assert "isn't VethuQ's" in " ".join(client.github.status("ghp_good").problems)

    def test_a_missing_workflow_and_secret(self, client, fake):
        client.github.setup("r", token="ghp_good")
        del fake.repo("octo/r")["files"][WORKFLOW]
        fake.repo("octo/r")["secrets"].clear()
        status = client.github.status("ghp_good")
        assert not status.ok and not status.secret_set
        assert {"The runner workflow is missing.", "The master key secret is missing."} <= set(
            status.problems
        )

    def test_a_missing_or_different_local_key(self, client, fake):
        from vethuq._paths import _Paths

        client.github.setup("r", token="ghp_good")
        path = _Paths.github_dir(client.db_path, create=False) / "master.key"
        path.write_text(_MasterKey.encode(b"q" * 32) + "\n")
        assert "isn't the one set up" in " ".join(client.github.status("ghp_good").problems)
        path.unlink()
        assert "missing on this computer" in " ".join(client.github.status("ghp_good").problems)

    def test_a_deleted_repository(self, client, fake):
        client.github.setup("r", token="ghp_good")
        del fake.repos["octo/r"]
        status = client.github.status("ghp_good")
        assert not status.repo_found and not status.ok and status.private is None

    def test_a_repository_made_public_is_noted_but_not_blocking(self, client, fake):
        client.github.setup("r", token="ghp_good")
        fake.repo("octo/r")["private"] = True
        fake.repo("octo/r")["private"] = False
        status = client.github.status("ghp_good")
        assert status.ok and any("public" in p for p in status.problems)

    def test_an_older_runner_is_out_of_date(self, client, fake, monkeypatch):
        from vethuq._github import template

        old = template._Row("github-tier-v0.0.9", "ghcr.io/coldsofttech/vethuq-worker:0.0.9", 1,
                            "0.1.0", "released")  # fmt: skip
        rows = [old, *_Compatibility.rows()]
        monkeypatch.setattr(template._Compatibility, "rows", staticmethod(lambda: rows))
        client.github.setup("r", token="ghp_good", workflow_ref="github-tier-v0.0.9")
        status = client.github.status("ghp_good")
        assert not status.up_to_date and status.ok  # old but sound
        assert any("newer runner" in p for p in status.problems)


class TestUpdateAndRemove:
    @pytest.fixture
    def two_versions(self, monkeypatch):
        from vethuq._github import template

        rows = [
            template._Row("github-tier-v0.0.9", "ghcr.io/coldsofttech/vethuq-worker:0.0.9", 1,
                          "0.1.0", "released"),
            *_Compatibility.rows(),
        ]  # fmt: skip
        monkeypatch.setattr(template._Compatibility, "rows", staticmethod(lambda: rows))

    def test_update_moves_the_pin_and_the_image(self, client, fake, two_versions):
        client.github.setup("r", token="ghp_good", workflow_ref="github-tier-v0.0.9")
        runner = client.github.update("ghp_good")
        assert runner.workflow_ref == "github-tier-v0.1.0"
        text = fake.repo("octo/r")["files"][WORKFLOW][0]
        assert _Caller.pin(text) == "github-tier-v0.1.0"
        assert _Caller.image(text).endswith(":0.1.0")
        assert client.github.runner() == runner
        assert client.github.status("ghp_good").up_to_date

    def test_update_to_a_chosen_version_and_only_listed_ones(self, client, fake, two_versions):
        client.github.setup("r", token="ghp_good")
        assert client.github.update("ghp_good", "github-tier-v0.0.9").workflow_ref.endswith("0.9")
        with pytest.raises(errors.GitHubSetupError):
            client.github.update("ghp_good", "evil")

    def test_update_repairs_a_changed_workflow_and_secret(self, client, fake):
        client.github.setup("r", token="ghp_good")
        fake.repo("octo/r")["files"][WORKFLOW] = (
            "name: edited\n",
            fake.repo("octo/r")["files"][WORKFLOW][1],
        )
        fake.repo("octo/r")["secrets"].clear()
        client.github.update("ghp_good")
        assert client.github.status("ghp_good").ok

    def test_update_needs_a_runner_and_a_repository(self, client, fake):
        with pytest.raises(errors.GitHubNotSetUpError):
            client.github.update("ghp_good")
        client.github.setup("r", token="ghp_good")
        del fake.repos["octo/r"]
        with pytest.raises(errors.GitHubSetupError, match="no longer exists"):
            client.github.update("ghp_good")

    def test_remove_forgets_but_keeps_the_repository_and_key(self, client, fake):
        from vethuq._paths import _Paths

        runner = client.github.setup("r", token="ghp_good")
        removed = client.github.remove()
        assert removed == runner and client.github.runner() is None
        assert "octo/r" in fake.repos
        assert (_Paths.github_dir(client.db_path, create=False) / "master.key").exists()

    def test_remove_can_delete_the_repository_and_the_key(self, client, fake):
        from vethuq._paths import _Paths

        client.github.setup("r", token="ghp_good")
        client.github.remove("ghp_good", delete_repo=True, delete_key=True)
        assert fake.repos == {}
        assert not (_Paths.github_dir(client.db_path, create=False) / "master.key").exists()

    def test_remove_with_nothing_set_up(self, client):
        with pytest.raises(errors.GitHubNotSetUpError):
            client.github.remove()

    def test_the_versions(self, client):
        (version,) = client.github.versions()
        assert isinstance(version, GitHubVersion) and version.status == "provisional"
        assert json.loads(version.to_json()) == version.to_dict()
        assert client.github.runner() is None


class TestKeys:
    def test_a_key_is_kept_once(self, tmp_path):
        keys = _MasterKey(tmp_path / "k")
        first = keys.obtain()
        assert keys.obtain() == first and keys.read() == first and keys.exists()
        assert keys.remove() and not keys.remove() and not keys.exists()

    def test_reading_a_missing_key(self, tmp_path):
        with pytest.raises(errors.GitHubSetupError, match="missing"):
            _MasterKey(tmp_path).read()

    def test_a_damaged_key_file(self, tmp_path):
        keys = _MasterKey(tmp_path)
        (tmp_path / "master.key").write_text("garbage\n")
        with pytest.raises(errors.GitHubSetupError, match="256-bit"):
            keys.read()

    def test_the_fingerprint_hides_the_key(self):
        key = _MasterKey.encode(b"a" * 32)
        assert len(_MasterKey.fingerprint(key)) == 8 and key[:8] not in _MasterKey.fingerprint(key)
