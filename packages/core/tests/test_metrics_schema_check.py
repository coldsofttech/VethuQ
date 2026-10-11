from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

SCHEMA = Path(__file__).resolve().parents[3] / "metrics" / "schema"


def load():
    spec = importlib.util.spec_from_file_location("metrics_schema_check", SCHEMA / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SchemaCheck


@pytest.fixture
def copy(tmp_path):
    shutil.copytree(SCHEMA / "v1", tmp_path / "v1")
    return tmp_path


class TestSchemaCheck:
    def test_the_published_schema_passes_every_check(self, capsys):
        assert load().main() == 0
        assert "ok" in capsys.readouterr().out

    def test_the_client_and_the_schema_name_the_same_fields(self):
        assert load()().check_client() == []

    def test_a_missing_client_is_skipped(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "vethuq._metrics", None)
        assert load()().check_client() is None

    def test_a_field_the_client_lacks_is_found(self, copy):
        path = copy / "v1" / "batch.schema.json"
        schema = json.loads(path.read_text())
        schema["properties"]["client"]["properties"]["hostname"] = {"type": "string"}
        path.write_text(json.dumps(schema))
        problems = load()(copy).check_client()
        assert len(problems) == 1 and "hostname" in problems[0]

    def test_an_example_on_the_wrong_side_is_found(self, copy):
        valid = copy / "v1" / "examples" / "valid-full.json"
        shutil.copy(valid, copy / "v1" / "examples" / "invalid-but-fine.json")
        problems = load()(copy).check_examples()
        assert problems == ["invalid-but-fine.json: expected invalid"]

    def test_an_example_with_an_unclear_name_is_found(self, copy):
        shutil.copy(
            copy / "v1" / "examples" / "valid-full.json", copy / "v1" / "examples" / "x.json"
        )
        assert "name it valid-*" in load()(copy).check_examples()[0]

    def test_no_examples_is_a_problem(self, copy):
        shutil.rmtree(copy / "v1" / "examples")
        (copy / "v1" / "examples").mkdir()
        assert load()(copy).check_examples() == ["there are no examples"]

    def test_a_broken_schema_is_found_and_run_fails(self, copy, capsys):
        (copy / "v1" / "delete.schema.json").write_text('{"type": 5}')
        check = load()(copy)
        assert check.check_schemas()[0].startswith("delete.schema.json")
        assert check.run() == 1
        assert "FAIL" in capsys.readouterr().out
