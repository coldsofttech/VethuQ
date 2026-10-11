"""The image's build files: checks that need no Docker."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = (ROOT / "github" / "image" / "Dockerfile").read_text()
BUILD = yaml.safe_load((ROOT / ".github" / "workflows" / "github-image.yml").read_text())
RUN = yaml.safe_load((ROOT / ".github" / "workflows" / "github-ocr.yml").read_text())


def steps(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


class TestDockerfile:
    def test_entrypoint_is_the_worker(self):
        assert 'ENTRYPOINT ["vethuq-worker"]' in DOCKERFILE

    def test_it_never_runs_as_root(self):
        users = re.findall(r"^USER (\S+)", DOCKERFILE, re.MULTILINE)
        assert users and users[-1] not in {"root", "0", "0:0"}

    def test_it_holds_no_secret(self):
        assert not re.search(r"^(ARG|ENV)\s+\S*(TOKEN|SECRET|KEY|PASSWORD)", DOCKERFILE, re.M)
        assert "PREMIUM_READ_TOKEN" not in DOCKERFILE

    def test_models_are_baked_and_found_at_runtime(self):
        assert "bake-models" in DOCKERFILE
        assert "VETHUQ_MODELS=/opt/vethuq/models" in DOCKERFILE

    def test_the_addons_the_workflow_builds_are_installed(self):
        installed = set(re.findall(r"vethuq-addon-[a-z-]+", DOCKERFILE))
        # A folder is named after the add-on, less the prefix its group drops (`ocr/modes/quick`
        # is `ocr-quick`).
        built = {
            "vethuq-addon-" + ("ocr-" if a.startswith("ocr/modes/") else "") + a.rsplit("/", 1)[-1]
            for a in BUILD["env"]["PREMIUM_ADDONS"].split()
        }
        assert installed == built


class TestBuildWorkflow:
    def test_triggers(self):
        triggers = BUILD[True]  # PyYAML reads the key `on` as True
        assert "workflow_dispatch" in triggers
        assert triggers["push"]["tags"] == ["worker-image-v*"]

    def test_only_the_build_job_may_write_packages(self):
        assert BUILD["permissions"] == {"contents": "read"}
        assert BUILD["jobs"]["image"]["permissions"]["packages"] == "write"

    def test_private_checkouts_use_the_read_token_and_keep_no_credentials(self):
        private = [s for s in steps(BUILD, "image") if "repository" in s.get("with", {})]
        assert len(private) == 2
        for step in private:
            assert step["with"]["token"] == "${{ secrets.PREMIUM_READ_TOKEN }}"
            assert step["with"]["persist-credentials"] is False

    def test_wheels_are_gated_and_admin_never_ships(self):
        script = next(s["run"] for s in steps(BUILD, "image") if "wheel_gate" in s.get("run", ""))
        assert "wheel_gate.py --wheel" in script
        assert "admin" in script

    def test_the_image_is_smoke_tested_without_a_network_before_it_is_pushed(self):
        names = [s.get("name", "") for s in steps(BUILD, "image")]
        smoke = next(s for s in steps(BUILD, "image") if s.get("name", "").startswith("Smoke"))
        assert "--network none" in smoke["run"]
        assert names.index(smoke["name"]) < names.index("Push")

    def test_version_is_validated(self):
        script = next(s["run"] for s in steps(BUILD, "image") if s.get("id") == "version")
        assert "bad version" in script


class TestRunnerWorkflowMatchesTheImage:
    def test_it_calls_the_entrypoint_with_run(self):
        script = next(s["run"] for s in steps(RUN, "ocr") if s.get("name") == "Run the worker")
        assert '"$IMAGE" run --job-id' in script
        assert "--network none" in script and "--cap-drop ALL" in script

    def test_image_name_it_allows_is_the_one_that_is_built(self):
        check = next(s for s in steps(RUN, "ocr") if s.get("name") == "Check the inputs")
        assert BUILD["env"]["IMAGE"].replace(".", r"\.") in check["run"]
