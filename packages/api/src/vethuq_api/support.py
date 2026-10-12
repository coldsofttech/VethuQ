"""The text a person pastes into a support request."""

from __future__ import annotations

from datetime import UTC, datetime


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_None._"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines


def _state(item: dict[str, object]) -> str:
    return "available" if item.get("available") else f"unavailable ({item.get('reason', '')})"


def build_report(
    *,
    about: dict[str, object],
    catalog: dict[str, list[dict[str, object]]],
    changed: list[dict[str, object]],
    data_location: str,
    now: datetime | None = None,
) -> str:
    """Markdown with the installation, what is installed, and the settings that were changed.

    It names no folder and no document, so it is safe to paste into a public issue.
    """
    moment = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "## VethuQ support information",
        "",
        f"- VethuQ: {about.get('vethuq')}",
        f"- Python: {about.get('python')}",
        f"- Platform: {about.get('platform')}",
        f"- Database schema: {about.get('db_schema')}",
        f"- Data folder: {data_location}",
        f"- Generated: {moment}",
        "",
        f"### Add-ons ({len(catalog['add_ons'])})",
        *_table(
            ["Name", "Version", "Status"],
            [[a["name"], a["version"], a["status"]] for a in catalog["add_ons"]],
        ),
        "",
        f"### File types ({len(catalog['file_types'])})",
        *_table(
            ["Name", "Extensions", "State"],
            [[f["label"], " ".join(f["extensions"]), _state(f)] for f in catalog["file_types"]],  # type: ignore[arg-type]
        ),
        "",
        f"### Search engines ({len(catalog['search_engines'])})",
        *_table(["Name", "State"], [[e["label"], _state(e)] for e in catalog["search_engines"]]),
        "",
        f"### Languages ({len(catalog['languages'])})",
        *_table(
            ["Name", "State"],
            [
                [
                    language["label"],
                    ("on" if language["enabled"] else "off") + ", " + _state(language),
                ]
                for language in catalog["languages"]
            ],
        ),
        "",
        f"### OCR engines ({len(catalog['ocr_engines'])})",
        *_table(
            ["Name", "Profiles", "State"],
            [[o["label"], ", ".join(o["profiles"]), _state(o)] for o in catalog["ocr_engines"]],  # type: ignore[arg-type]
        ),
        "",
        "### Settings changed from the default",
    ]
    if changed:
        lines += [
            f"- {item['label']} (`{item['id']}`): {_describe(item['value'])}" for item in changed
        ]
    else:
        lines.append("_None._")
    return "\n".join(lines) + "\n"


def _describe(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)
