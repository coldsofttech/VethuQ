import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from vethuq_core.ocr import JsonReader, Readers, StructuredReader, YamlReader
from vethuq_core.ocr.structured import StructuredText


class TestFlatten:
    def test_nested_objects_and_lists_use_paths(self):
        data = {"server": {"host": "localhost", "ports": [8080, 8443]}, "debug": True}

        assert StructuredText.flatten(data).splitlines() == [
            "server.host: localhost",
            "server.ports[0]: 8080",
            "server.ports[1]: 8443",
            "debug: true",
        ]

    def test_scalars_render_json_style(self):
        text = StructuredText.flatten({"a": None, "b": False, "c": 1.5, "d": "x"})

        assert text.splitlines() == ["a: null", "b: false", "c: 1.5", "d: x"]

    def test_root_list_and_root_scalar(self):
        assert StructuredText.flatten([{"id": 1}]) == "[0].id: 1"
        assert StructuredText.flatten("just text") == "just text"

    def test_empty_containers_keep_their_key(self):
        assert StructuredText.flatten({"a": {}, "b": []}).splitlines() == ["a: {}", "b: []"]

    def test_non_string_keys_and_sets_are_stringified(self):
        text = StructuredText.flatten({1: "one", "tags": {"b", "a"}})

        assert text.splitlines() == ["1: one", "tags[0]: a", "tags[1]: b"]

    def test_dates_and_binary(self):
        loaded = yaml.safe_load("when: 2026-01-02\nblob: !!binary aGVsbG8=")

        assert StructuredText.flatten(loaded).splitlines() == [
            "when: 2026-01-02",
            "blob: <binary 5 bytes>",
        ]

    def test_self_referencing_container_is_skipped_not_looped(self):
        recursive: dict[str, object] = {"name": "loop"}
        recursive["self"] = recursive

        assert StructuredText.flatten(recursive) == "name: loop"

    def test_shared_alias_is_expanded_each_time_it_is_used(self):
        loaded = yaml.safe_load("base: &b {k: v}\na: *b\nb: *b")

        assert StructuredText.flatten(loaded).splitlines() == ["base.k: v", "a.k: v", "b.k: v"]

    def test_expansion_over_the_cap_is_rejected(self):
        # A "billion laughs" shape: tiny input, enormous flattened output.
        layers = ["a: &a0 [x, x, x, x, x, x, x, x, x, x]"]
        layers += [f"{chr(98 + i)}: &a{i + 1} [{', '.join([f'*a{i}'] * 10)}]" for i in range(8)]
        loaded = yaml.safe_load("\n".join(layers))

        with patch.object(StructuredText, "MAX_TEXT_CHARS", 10_000):
            with pytest.raises(ValueError, match="too large"):
                StructuredText.flatten(loaded)

    def test_deep_nesting_does_not_hit_the_recursion_limit(self):
        node: object = "leaf"
        for _ in range(900):
            node = [node]

        assert StructuredText.flatten(node).endswith("]: leaf")


class TestDecode:
    def test_utf8(self):
        assert StructuredText.decode("héllo".encode()) == "héllo"

    def test_utf8_bom_is_stripped(self):
        assert StructuredText.decode(b"\xef\xbb\xbf" + b'{"a": 1}') == '{"a": 1}'

    def test_utf16_with_bom(self):
        assert StructuredText.decode('{"a": 1}'.encode("utf-16")) == '{"a": 1}'

    def test_invalid_utf8_falls_back_to_cp1252(self):
        assert StructuredText.decode("café".encode("cp1252")) == "café"


class TestFromJson:
    def test_duplicate_keys_are_all_indexed(self):
        assert StructuredText.from_json('{"a": 1, "a": 2}').splitlines() == ["a: 1", "a: 2"]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            StructuredText.from_json("{not json")


class TestFromYaml:
    def test_multiple_documents_are_joined(self):
        text = StructuredText.from_yaml("a: 1\n---\nb: 2\n")

        assert text == "a: 1\n\nb: 2"

    def test_unsafe_tag_is_rejected_rather_than_constructed(self):
        with pytest.raises(yaml.YAMLError):
            StructuredText.from_yaml("x: !!python/object/apply:os.system ['echo hi']")


class TestStructuredReader:
    def test_suffixes_are_registered(self):
        for name, reader_type in (
            ("a.json", JsonReader),
            ("a.JSON", JsonReader),
            ("a.yaml", YamlReader),
            ("a.yml", YamlReader),
        ):
            reader = Readers.for_path(Path(name))
            assert isinstance(reader, reader_type)
            assert reader.file_type == "structured"
            assert Readers.is_supported(Path(name))

    def test_new_file_type_counts_include_structured(self):
        assert Readers.new_file_type_counts() == {"pdf": 0, "image": 0, "structured": 0}

    def test_iter_files_finds_json_and_yaml_only(self, tmp_path):
        for name in ("a.json", "b.yaml", "c.yml", "d.txt", "e.toml"):
            (tmp_path / name).write_text("{}")

        found = sorted(path.name for path in Readers.iter_files(tmp_path))

        assert found == ["a.json", "b.yaml", "c.yml"]

    def test_json_reader_returns_one_native_page(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"name": "vethuq", "tags": ["ocr"]}))

        (page,) = JsonReader().ocr(conn, path)

        assert page.text == "name: vethuq\ntags[0]: ocr"
        assert page.confidence == 1.0
        assert page.source == "native"
        assert page.ocr_engine is None

    def test_yaml_reader_reads_documents(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("name: vethuq\nlist:\n  - one\n  - two\n")

        (page,) = YamlReader().ocr(conn, path)

        assert page.text == "name: vethuq\nlist[0]: one\nlist[1]: two"

    def test_invalid_file_is_indexed_as_raw_text(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "template.yaml"
        path.write_text("name: {{ .Values.name }}\nreplicas: [")

        (page,) = YamlReader().ocr(conn, path)

        assert page.text == "name: {{ .Values.name }}\nreplicas: ["

    def test_empty_file_gives_an_empty_page(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")

        (page,) = YamlReader().ocr(conn, path)

        assert page.text == ""

    def test_oversized_file_is_rejected(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "big.json"
        path.write_text("[]")

        with patch.object(StructuredText, "MAX_FILE_BYTES", 1):
            with pytest.raises(ValueError, match="limit"):
                JsonReader().ocr(conn, path)

    def test_base_class_parse_is_abstract(self):
        with pytest.raises(NotImplementedError):
            StructuredReader().parse("x")
