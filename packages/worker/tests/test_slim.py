"""The script that drops what a running worker never reads from the image's Python tree."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SLIM = Path(__file__).resolve().parents[3] / "github" / "image" / "slim.py"
spec = importlib.util.spec_from_file_location("slim", SLIM)
slim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slim)


def tree(root: Path) -> Path:
    site = root / "lib" / "python3.12" / "site-packages"
    files = {
        "pkg/__init__.py": "x = 1",
        "pkg/core.py": "y = 2",
        "pkg/__pycache__/core.cpython-312.pyc": "bytecode",
        "pkg/tests/__init__.py": "",
        "pkg/tests/test_core.py": "def test(): ...",
        "pkg/sub/test/helper.py": "",
        "pkg/docs/index.md": "docs",
        "pkg/examples/demo.py": "",
        "pkg/include/pkg.h": "#define X",
        "pkg/native.so": "binary",
        "pkg/data/model.json": "{}",
        "pkg/testing/__init__.py": "# a module other code imports",
        "pkg-1.0.dist-info/METADATA": "licence",
        "pkg-1.0.dist-info/entry_points.txt": "[console_scripts]",
        "pkg-1.0.dist-info/tests/kept.txt": "even this stays: it is in a dist-info",
        "tests/__init__.py": "",  # a stray top-level `tests` is a package too: left alone
    }
    for name, text in files.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return site


def names(site: Path) -> set[str]:
    return {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}


def test_it_removes_byte_code_tests_docs_examples_and_headers(tmp_path):
    site = tree(tmp_path)

    removed = slim.Slimmer(tmp_path).run()

    left = names(site)
    assert removed > 0
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in left)
    assert not any(
        n.startswith(("pkg/tests", "pkg/sub/test", "pkg/docs", "pkg/examples")) for n in left
    )
    assert "pkg/include/pkg.h" not in left


def test_it_keeps_what_the_package_imports_and_loads(tmp_path):
    site = tree(tmp_path)
    slim.Slimmer(tmp_path).run()

    left = names(site)
    assert {"pkg/__init__.py", "pkg/core.py", "pkg/native.so", "pkg/data/model.json"} <= left
    assert "pkg/testing/__init__.py" in left  # `testing` is a module, not a test suite


def test_it_never_touches_a_dist_info(tmp_path):
    site = tree(tmp_path)
    slim.Slimmer(tmp_path).run()

    left = names(site)
    assert {
        "pkg-1.0.dist-info/METADATA",
        "pkg-1.0.dist-info/entry_points.txt",
        "pkg-1.0.dist-info/tests/kept.txt",
    } <= left


def test_a_top_level_tests_folder_is_left_alone(tmp_path):
    site = tree(tmp_path)
    slim.Slimmer(tmp_path).run()

    assert "tests/__init__.py" in names(site)


def test_running_it_again_changes_nothing(tmp_path):
    site = tree(tmp_path)
    slim.Slimmer(tmp_path).run()
    once = names(site)

    assert slim.Slimmer(tmp_path).run() == 0
    assert names(site) == once


def test_it_only_looks_inside_site_packages(tmp_path):
    outside = tmp_path / "bin" / "tests" / "keep.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("")
    tree(tmp_path)

    slim.Slimmer(tmp_path).run()

    assert outside.exists()


def test_the_command_reports_and_needs_a_folder(tmp_path, capsys):
    tree(tmp_path)

    assert slim.main([str(tmp_path)]) == 0
    assert "removed" in capsys.readouterr().out
    assert slim.main([]) == 2


@pytest.mark.parametrize("name", ["pkg/__init__.py", "pkg/native.so"])
def test_a_linked_file_is_not_followed_out_of_the_tree(tmp_path, name):
    site = tree(tmp_path)
    target = tmp_path / "outside.h"
    target.write_text("keep")
    (site / "pkg" / "link.h").symlink_to(target)

    slim.Slimmer(tmp_path).run()

    assert target.read_text() == "keep"
