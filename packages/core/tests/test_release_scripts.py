"""The release scripts: what a tag releases, and merging the compiled runtime into a wheel."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "release"


def load(name):
    spec = importlib.util.spec_from_file_location(f"release_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plan = load("plan")
merge_wheel = load("merge_wheel")


class TestPlan:
    @pytest.mark.parametrize(
        ("tag", "dist", "directory", "platform"),
        [
            ("vethuq-addon-api-v0.11.0", "vethuq-addon-api", "packages/addon-api", False),
            ("vethuq-worker-v1.2.3", "vethuq-worker", "packages/worker", False),
            ("vethuq-v1.0.0", "vethuq", "packages/core", True),
        ],
    )
    def test_each_package_has_its_tag(self, tag, dist, directory, platform):
        release = plan.plan(tag)
        assert (release.dist, release.directory, release.platform_wheels) == (
            dist,
            directory,
            platform,
        )
        assert release.prerelease is False

    def test_a_release_candidate_is_a_prerelease_with_a_normal_version(self):
        release = plan.plan("vethuq-v1.0.0-rc2")
        assert release.version == "1.0.0rc2" and release.prerelease

    @pytest.mark.parametrize("tag", ["v1.0.0", "cli-v1.0.0", "vethuq-1.0.0", "vethuq-core-v1.0.0"])
    def test_other_tags_are_refused(self, tag):
        with pytest.raises(plan.ReleaseError, match="not a release tag"):
            plan.plan(tag)

    def test_wheels_must_carry_the_tags_version(self):
        release = plan.plan("vethuq-worker-v1.2.3")
        plan.check_wheels(release, ["dist/vethuq_worker-1.2.3-py3-none-any.whl"])
        with pytest.raises(plan.ReleaseError, match="not 1.2.3"):
            plan.check_wheels(release, ["dist/vethuq_worker-1.2.4-py3-none-any.whl"])
        with pytest.raises(plan.ReleaseError, match="is not a vethuq-worker wheel"):
            plan.check_wheels(release, ["dist/vethuq-1.2.3-py3-none-any.whl"])
        with pytest.raises(plan.ReleaseError, match="Nothing was built"):
            plan.check_wheels(release, [])

    def test_main(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        assert plan.main(["vethuq-v1.0.0"]) == 0
        assert "platform_wheels=true" in out.read_text()
        assert plan.main(["bad"]) == 1
        assert plan.main([]) == 2
        assert plan.main(["vethuq-v1.0.0", "--wheels", "x/vethuq-1.0.0-py3-none-any.whl"]) == 0
        assert "carry 1.0.0" in capsys.readouterr().out


def build_wheel(path: Path, files: dict[str, bytes], tag: str) -> Path:
    stem = path.name.split("-")
    dist_info = f"{stem[0]}-{stem[1]}.dist-info"
    with zipfile.ZipFile(path, "w") as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)
        wheel.writestr(f"{dist_info}/METADATA", f"Name: {stem[0]}\nVersion: {stem[1]}\n")
        wheel.writestr(
            f"{dist_info}/WHEEL", f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {tag}\n"
        )
        wheel.writestr(f"{dist_info}/RECORD", "")
    return path


@pytest.fixture
def wheels(tmp_path):
    pure = build_wheel(
        tmp_path / "vethuq-1.0.0-py3-none-any.whl",
        {"vethuq/__init__.py": b"x = 1\n"},
        "py3-none-any",
    )
    runtime = build_wheel(
        tmp_path / "vethuq_entitlements-0.1.0-cp311-abi3-manylinux_2_17_x86_64.whl",
        {
            "vethuq_entitlements/__init__.py": b"from .licences import Licences\n",
            "vethuq_entitlements/licences.abi3.so": b"\x7fELF",
        },
        "cp311-abi3-manylinux_2_17_x86_64",
    )
    return pure, runtime


class TestMerge:
    def test_the_result_has_both_and_is_tagged_for_the_platform(self, wheels, tmp_path):
        target = merge_wheel.merge(*wheels, tmp_path / "out")
        assert target.name == "vethuq-1.0.0-cp311-abi3-manylinux_2_17_x86_64.whl"
        with zipfile.ZipFile(target) as merged:
            names = set(merged.namelist())
            assert {"vethuq/__init__.py", "vethuq_entitlements/licences.abi3.so"} <= names
            wheel = merged.read("vethuq-1.0.0.dist-info/WHEEL").decode()
        assert "Tag: cp311-abi3-manylinux_2_17_x86_64" in wheel
        assert "Root-Is-Purelib: false" in wheel

    def test_the_record_lists_every_file_with_its_hash(self, wheels, tmp_path):
        target = merge_wheel.merge(*wheels, tmp_path / "out")
        with zipfile.ZipFile(target) as merged:
            rows = [
                line.split(",")
                for line in merged.read("vethuq-1.0.0.dist-info/RECORD").decode().splitlines()
            ]
            for name, digest, size in rows:
                if name.endswith("/RECORD"):
                    assert digest == "" and size == ""
                    continue
                data = merged.read(name)
                assert digest == merge_wheel.hashed(data) and int(size) == len(data)
        assert {r[0] for r in rows} == set(zipfile.ZipFile(target).namelist())

    def test_it_does_not_add_a_dependency_on_entitlements(self, wheels, tmp_path):
        target = merge_wheel.merge(*wheels, tmp_path / "out")
        with zipfile.ZipFile(target) as merged:
            assert (
                "Requires-Dist: vethuq-entitlements"
                not in merged.read("vethuq-1.0.0.dist-info/METADATA").decode()
            )

    def test_a_platform_wheel_given_as_the_pure_one_is_refused(self, wheels, tmp_path):
        pure, runtime = wheels
        with pytest.raises(merge_wheel.MergeError, match="not a pure-Python"):
            merge_wheel.merge(runtime, runtime, tmp_path / "out")
        with pytest.raises(merge_wheel.MergeError, match="not a cp311-abi3"):
            merge_wheel.merge(pure, pure, tmp_path / "out")

    def test_a_runtime_wheel_without_the_package_is_refused(self, wheels, tmp_path):
        pure, _ = wheels
        empty = build_wheel(
            tmp_path / "vethuq_entitlements-0.1.0-cp311-abi3-win_amd64.whl",
            {"other/x.py": b""},
            "cp311-abi3-win_amd64",
        )
        with pytest.raises(merge_wheel.MergeError, match="no vethuq_entitlements package"):
            merge_wheel.merge(pure, empty, tmp_path / "out")

    def test_main(self, wheels, tmp_path, capsys):
        pure, runtime = wheels
        assert merge_wheel.main([str(pure), str(runtime), "--out", str(tmp_path / "o")]) == 0
        assert "cp311-abi3" in capsys.readouterr().out
        assert merge_wheel.main([str(pure), str(pure), "--out", str(tmp_path / "o")]) == 1
        assert merge_wheel.main([]) == 2

    def test_pip_can_read_the_result(self, wheels, tmp_path):
        """The merged file is a well-formed wheel: its dist-info is complete and its tags parse."""
        from packaging.utils import parse_wheel_filename

        target = merge_wheel.merge(*wheels, tmp_path / "out")
        name, version, _build, tags = parse_wheel_filename(target.name)
        assert (str(name), str(version)) == ("vethuq", "1.0.0")
        assert {str(t) for t in tags} == {"cp311-abi3-manylinux_2_17_x86_64"}
