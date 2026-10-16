"""The image's build files: checks that need no Docker."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from vethuq_worker import variants

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = (ROOT / "github" / "image" / "Dockerfile").read_text()
BUILD = yaml.safe_load((ROOT / ".github" / "workflows" / "github-image.yml").read_text())
RUN = yaml.safe_load((ROOT / ".github" / "workflows" / "github-ocr.yml").read_text())
SMOKE = (ROOT / "github" / "image" / "smoke.sh").read_text()


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

    def test_the_models_are_not_in_the_image_only_their_lock(self):
        # They are downloaded in a throwaway stage to write the lock; the final stage copies the
        # lock and nothing else from it, and is where the models folder is only a mount point.
        final = DOCKERFILE[DOCKERFILE.index("FROM variant AS final") :]
        assert "bake-models" in DOCKERFILE and "bake-models" not in final
        assert "COPY --from=locked /opt/vethuq/models.lock.json" in final
        assert re.findall(r"COPY --from=locked (\S+)", final) == ["/opt/vethuq/models.lock.json"]
        assert "VETHUQ_MODELS=/opt/vethuq/models" in final
        assert "VETHUQ_MODELS_LOCK=/opt/vethuq/models.lock.json" in final

    def test_the_wheels_are_mounted_not_copied_so_no_layer_holds_them(self):
        assert "COPY wheels" not in DOCKERFILE
        assert DOCKERFILE.count("--mount=type=bind,source=wheels,target=/wheels") == 2

    def test_every_variant_starts_from_the_same_base_stage(self):
        assert "FROM os AS base" in DOCKERFILE and "FROM base AS variant" in DOCKERFILE
        assert "ARG VARIANT" in DOCKERFILE and "COPY lists/${VARIANT}.txt" in DOCKERFILE

    def test_the_layers_are_slimmed_and_carry_no_byte_code_or_documentation(self):
        assert DOCKERFILE.count("python /slim.py /opt/venv") == 2
        assert "--no-compile" in DOCKERFILE
        assert "/usr/share/doc" in DOCKERFILE and "--no-install-recommends" in DOCKERFILE

    def test_the_environment_has_no_pip_of_its_own(self):
        assert "venv --without-pip" in DOCKERFILE

    def test_the_addons_the_workflow_builds_are_the_ones_the_variants_name(self):
        built = {
            "vethuq-addon-" + ("ocr-" if a.startswith("ocr/modes/") else "") + a.rsplit("/", 1)[-1]
            for a in BUILD["env"]["PREMIUM_ADDONS"].split()
        }
        assert built == set(variants.everything())


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

    def test_every_variant_is_smoke_tested_before_anything_is_pushed(self):
        names = [s.get("name", "") for s in steps(BUILD, "image")]
        build = next(s for s in steps(BUILD, "image") if s.get("id") == "build")
        assert "smoke.sh" in build["run"] and "--load" in build["run"]
        assert 'python "$variants" --names' in build["run"]
        assert names.index(build["name"]) < names.index("Push")

    def test_the_smoke_test_covers_the_models_flow(self):
        text = SMOKE
        # no models: refused; fetch with a network; read with none; a changed model: refused
        assert "models_missing" in text and "models_unverified" in text
        assert "fetch-models" in text
        assert text.index("fetch-models") < text.index("== 3.")
        job = re.search(r"run_job\(\) \{.*?\n\}", text, re.S).group(0)
        assert "--network none" in job and "-e VETHUQ_MASTER_KEY" in job
        fetch = next(line for line in text.splitlines() if line.rstrip().endswith("fetch-models"))
        assert "VETHUQ_MASTER_KEY" not in fetch and "/payload" not in fetch
        assert "--network" not in fetch  # the one step that has a network

    def test_the_images_are_pushed_compressed_and_tagged_by_variant(self):
        push = next(s for s in steps(BUILD, "image") if s.get("name") == "Push")
        assert "compression=zstd" in push["run"] and "force-compression=true" in push["run"]
        assert "$IMAGE:$VERSION-$variant" in push["run"]
        assert '[ "$variant" = full ] && tags+=(--tag "$IMAGE:$VERSION")' in push["run"]

    def test_the_compatibility_row_names_every_variants_image(self):
        row = next(s for s in steps(BUILD, "image") if s.get("name") == "Compatibility row")
        assert '"variants": images' in row["run"] and '"image": images["full"]' in row["run"]

    def test_the_lists_the_dockerfile_reads_are_written_from_the_variants(self):
        step = next(
            s for s in steps(BUILD, "image") if s.get("name", "").startswith("Write the add-on")
        )
        assert "--list slim" in step["run"] and "--extra" in step["run"]
        assert "no wheel for" in step["run"]

    def test_version_is_validated(self):
        script = next(s["run"] for s in steps(BUILD, "image") if s.get("id") == "version")
        assert "bad version" in script


class TestRunnerWorkflowMatchesTheImage:
    def named(self, name):
        return next(s for s in steps(RUN, "ocr") if s.get("name") == name)

    def test_it_calls_the_entrypoint_with_run(self):
        script = self.named("Run the worker")["run"]
        assert '"$IMAGE" run --job-id' in script
        assert "--network none" in script and "--cap-drop ALL" in script

    def test_image_name_it_allows_is_the_one_that_is_built(self):
        check = self.named("Check the inputs")
        assert BUILD["env"]["IMAGE"].replace(".", r"\.") in check["run"]

    def test_a_variant_is_looked_up_in_the_callers_map_before_the_key_is_used(self):
        names = [s.get("name") for s in steps(RUN, "ocr")]
        check = self.named("Check the inputs")
        assert "jq -r --arg v \"$VARIANT\" '.[$v] // empty'" in check["run"]
        assert "variant not offered" in check["run"] and "bad variant" in check["run"]
        assert names.index("Check the inputs") < names.index("Run the worker")
        for name in ("Pull the worker image", "Run the worker"):
            assert "steps.check.outputs.image" in str(self.named(name)["env"])

    def test_the_key_is_only_in_the_step_that_runs_with_no_network(self):
        holders = [s["name"] for s in steps(RUN, "ocr") if "master_key" in str(s.get("env", ""))]
        assert holders == ["Run the worker"]
        assert "--network none" in self.named("Run the worker")["run"]

    def test_the_models_download_has_a_network_but_neither_the_key_nor_the_payload(self):
        fetch = self.named("Download the OCR models (first run only)")
        assert "fetch-models" in fetch["run"] and "--network none" not in fetch["run"]
        assert "master_key" not in str(fetch) and "/payload" not in fetch["run"]
        assert "--cap-drop ALL" in fetch["run"] and "no-new-privileges" in fetch["run"]

    def test_the_models_are_cached_by_the_images_lock_and_saved_before_the_job_runs(self):
        names = [s.get("name") for s in steps(RUN, "ocr")]
        restore, save = (
            self.named("Restore the OCR models"),
            self.named("Keep the OCR models for the next job"),
        )
        assert restore["uses"].startswith("actions/cache/restore@")
        assert save["uses"].startswith("actions/cache/save@")
        assert restore["with"]["key"] == save["with"]["key"] == "${{ steps.lock.outputs.key }}"
        assert "models.lock.json" in self.named("Work out the models cache key")["run"]
        assert (
            names.index("Restore the OCR models")
            < names.index("Download the OCR models (first run only)")
            < names.index("Keep the OCR models for the next job")
            < names.index("Run the worker")
        )

    def test_the_job_gets_the_models_read_only(self):
        assert (
            '-v "$RUNNER_TEMP/models:/opt/vethuq/models:ro"' in self.named("Run the worker")["run"]
        )

    def test_the_caller_can_pass_a_map_of_images_and_a_variant(self):
        inputs = RUN[True]["workflow_call"]["inputs"]
        assert inputs["images"]["default"] == "{}" and inputs["variant"]["default"] == ""
        assert inputs["images"]["required"] is False and inputs["variant"]["required"] is False
