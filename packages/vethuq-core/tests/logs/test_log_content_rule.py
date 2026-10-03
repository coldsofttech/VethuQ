"""Lint-style rule: log statements never reference document content or search queries.

Logs may carry paths, ids, counts and error types - not extracted text (`ocr_text`,
`native_text`, page text) or what a user searched for, since log files outlive
the documents' own access controls. A finding here means a log call was passed
one of those names; log a length/count/id instead.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

_PACKAGES = Path(__file__).resolve().parents[3]


class LogContentRule:
    LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    LOGGER_NAMES = {"_logger", "logger"}
    SENSITIVE = {
        "ocr_text",
        "native_text",
        "text",
        "combined_text",
        "page_text",
        "content",
        "query",
        "matched",
        "before",
        "after",
        "snippet",
    }

    @staticmethod
    def names_in(node: ast.AST) -> set[str]:
        """Bare variable/attribute names an expression uses - but not inside `len(...)` etc.

        A call's own arguments are skipped so `len(query)` is fine, while the
        call's target (`page.native_text.strip()`) still counts.
        """
        found: set[str] = set()

        def visit(n: ast.AST) -> None:
            if isinstance(n, ast.Name):
                found.add(n.id)
            elif isinstance(n, ast.Attribute):
                found.add(n.attr)
                visit(n.value)
            elif isinstance(n, ast.Call):
                visit(n.func)  # the arguments (e.g. len(x)) are derived values, not the content
            else:
                for child in ast.iter_child_nodes(n):
                    visit(child)

        visit(node)
        return found

    @staticmethod
    def log_calls(tree: ast.AST) -> Iterator[ast.Call]:
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LogContentRule.LOG_METHODS
            ):
                continue
            target = node.func.value
            name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
            if name in LogContentRule.LOGGER_NAMES:
                yield node

    @staticmethod
    def source_files() -> list[Path]:
        return sorted(_PACKAGES.glob("*/src/**/*.py"))

    @staticmethod
    def sensitive_names(call: ast.Call) -> set[str]:
        # args[0] is the format string; the rest (and keywords) are values.
        values = [*call.args[1:], *(kw.value for kw in call.keywords if kw.arg != "exc_info")]
        if not values:
            return set()
        return set().union(*(LogContentRule.names_in(v) for v in values)) & (
            LogContentRule.SENSITIVE
        )


class TestLogContentRule:
    def test_source_files_are_found(self):
        assert LogContentRule.source_files()

    @pytest.mark.parametrize(
        "path", LogContentRule.source_files(), ids=lambda p: str(p.relative_to(_PACKAGES))
    )
    def test_log_calls_do_not_reference_document_content(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = []
        for call in LogContentRule.log_calls(tree):
            bad = LogContentRule.sensitive_names(call)
            if bad:
                offenders.append(f"{path.name}:{call.lineno} logs {sorted(bad)}")
        assert not offenders, "; ".join(offenders)

    def test_rule_flags_content_names(self):
        tree = ast.parse('_logger.info("saw %s", ocr_text)\n_logger.info("n=%d", len(ocr_text))')
        flagged = [c for c in LogContentRule.log_calls(tree) if LogContentRule.sensitive_names(c)]
        assert len(flagged) == 1
