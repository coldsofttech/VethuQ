"""(Re)generate `expected.json` for a folder of integration-test fixtures by really OCR'ing them.

    uv run python scripts/dev/generate_integration_expected.py      # fixtures/en/pdf
    uv run python scripts/dev/generate_integration_expected.py --lang te \\
        --dir packages/vethuq-core/tests/integration/fixtures/te/pdf

It indexes every file in the folder with the real engines (the OCR models must be downloaded,
`vethuq ocr models download`), then records what it found: status, page count and, per page, how the
text was got (`native` / `ocr` / `mixed`), the OCR confidence and phrases the page must contain.

Phrases already in `expected.json` are kept, since a person chose them; the script only fills pages
that have none. It never overwrites a hand-written entry for a file it could not read (for example
when the models are missing): that entry is left as it was and listed at the end. Review the phrases
it adds, because they come from the OCR output itself and may hold its mistakes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO / "packages/vethuq-core/tests/integration/fixtures/en/pdf"
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_PHRASES = 3


def distinctive_lines(text: str) -> list[str]:
    """Up to `MAX_PHRASES` lines worth asserting on: long enough, mostly letters."""
    found = []
    for line in text.splitlines():
        line = " ".join(line.split())
        letters = sum(ch.isalpha() for ch in line)
        if len(line) >= 16 and len(line.split()) >= 3 and letters / len(line) >= 0.7:
            found.append(line)
        if len(found) == MAX_PHRASES:
            break
    return found


def floor_to(value: float, step: float = 0.05) -> float:
    return round(math.floor(value / step) * step, 2)


def read_in(row) -> list[str]:
    """The languages a stored page was read in (English when none was recorded)."""
    langs = {part for part in (row["ocr_langs"] or "").split(",") if part}
    if row["language"]:
        langs.add(row["language"])
    return sorted(langs or {"en"})


def read_file(path: Path, language: str, engine: str | None = None) -> dict | None:
    """Index `path` for real; the entry found, or None if it could not be read (models, network)."""
    sys.path.insert(0, str(REPO / "packages/vethuq-core/src"))
    from vethuq_core.db import Db
    from vethuq_core.ocr import Ocr
    from vethuq_core.paths import Paths
    from vethuq_core.sources import Sources
    from vethuq_core.storage.sqlite import SqliteStorage

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        Paths.default_data_root = staticmethod(lambda: root / "data")  # type: ignore[method-assign]
        Paths.platform_data_root = staticmethod(lambda: root / "data")  # type: ignore[method-assign]
        folder = root / "docs"
        folder.mkdir()
        shutil.copy(path, folder / path.name)
        conn = Db.connect(root / "vethuq.db")
        try:
            storage = SqliteStorage(conn)
            if engine:
                from vethuq_core.settings import OcrSettings

                OcrSettings.set_engine(storage, engine)
            source = Sources.add(storage, folder, languages=language)
            Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
            doc = conn.execute("SELECT status, error_message FROM document_index").fetchone()
            if doc["status"] == "error" and re.search(
                r"model|download|network|connection|OCR engine", doc["error_message"] or "", re.I
            ):
                return None
            entry: dict = {"file": path.name, "status": doc["status"], "verified": True}
            pages = conn.execute(
                "SELECT page_number, ocr_text, confidence, source, language, "
                "ocr_langs FROM pdf_pages "
                "UNION ALL SELECT 1, ocr_text, confidence, 'ocr', language, ocr_langs "
                "FROM image_pages "
                "ORDER BY 1"
            ).fetchall()
            entry["page_count"] = len(pages)
            entry["pages"] = {}
            for page in pages:
                number = page["page_number"]
                if len(pages) > 5 and number not in (1, len(pages)):
                    continue  # a long document: its first and last pages are enough to pin
                info: dict = {
                    "source": page["source"],
                    "read_in": read_in(page),
                    "contains": distinctive_lines(page["ocr_text"]),
                }
                if page["source"] != "native":
                    info["min_confidence"] = floor_to(page["confidence"] - 0.1)
                entry["pages"][str(page["page_number"])] = info
            return entry
        finally:
            conn.close()


def merge(old: dict | None, new: dict) -> dict:
    """`new`, keeping the phrases a person already chose in `old`."""
    if old is None:
        return new
    for key in ("languages", "engine", "searches", "note", "lang_en"):
        if key in old:
            new[key] = old[key]
    for number, info in new["pages"].items():
        before = old.get("pages", {}).get(number, {})
        if before.get("contains"):
            info["contains"] = before["contains"]
        if "note" in before:
            info["note"] = before["note"]
    return new


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder of fixture files")
    parser.add_argument("--lang", default="en", help="language the files are read in (en, te, ...)")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="PREFIX",
        help="only the files whose names start with one of these (e.g. 06 07); the rest of "
        "expected.json is left as it is",
    )
    args = parser.parse_args()

    target = args.dir / "expected.json"
    document = json.loads(target.read_text("utf-8")) if target.exists() else {"files": []}
    document.update(language=args.lang, file_type=args.dir.name)
    by_name = {entry["file"]: entry for entry in document["files"]}

    unread = []
    for path in sorted(args.dir.iterdir()):
        if path.suffix.lower() not in SUFFIXES:
            continue
        if args.only and not path.name.startswith(tuple(args.only)):
            continue
        print(f"reading {path.name} ...", flush=True)
        old = by_name.get(path.name) or {}
        entry = read_file(path, old.get("languages", args.lang), old.get("engine"))
        if entry is None:
            unread.append(path.name)
            by_name.setdefault(path.name, {"file": path.name, "verified": False})
            continue
        by_name[path.name] = merge(by_name.get(path.name), entry)

    document["files"] = [by_name[name] for name in sorted(by_name)]
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {target}")
    if unread:
        print("could not be read for real (kept as they were):", *unread, sep="\n  ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
