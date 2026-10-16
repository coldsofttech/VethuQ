"""`python -m tools.ocr_accuracy`: read the test pages with the real engine and score them.

    python -m tools.ocr_accuracy --out report.json --summary summary.md
    python -m tools.ocr_accuracy --phases quick --pages clean,scan
    python -m tools.ocr_accuracy --suggest suggested.json    (limits today's scores would pass)

Exits with status 1 when a case fails. Needs the installed OCR add-ons and, the first time, the
network for the models.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import vethuq
from tools.ocr_accuracy import pages, suite
from tools.ocr_accuracy.engines import ClientReader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.ocr_accuracy", description=__doc__)
    parser.add_argument("--phases", help="comma-separated OCR phases (default: all installed)")
    parser.add_argument("--languages", default="en", help="comma-separated language ids")
    parser.add_argument(
        "--pages", help=f"comma-separated page types: {', '.join(pages.PAGE_TYPES)}"
    )
    parser.add_argument("--thresholds", type=Path, default=suite.THRESHOLDS)
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    parser.add_argument("--summary", type=Path, help="append a Markdown table here")
    parser.add_argument("--suggest", type=Path, help="write limits that these scores would pass")
    args = parser.parse_args(argv)

    thresholds = suite.load_thresholds(args.thresholds)
    page_types = args.pages.split(",") if args.pages else list(pages.PAGE_TYPES)
    unknown = [p for p in page_types if p not in pages.PAGE_TYPES]
    if unknown:
        parser.error(f"unknown page types: {', '.join(unknown)}")
    with (
        tempfile.TemporaryDirectory() as home,
        vethuq.VethuQ(db_path=Path(home) / "v.db") as client,
    ):
        reader = ClientReader(client)
        phases = args.phases.split(",") if args.phases else reader.phases()
        report = suite.run(reader, phases, args.languages.split(","), page_types, thresholds)
    if args.out:
        args.out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as stream:
            stream.write(report.markdown())
    if args.suggest:
        args.suggest.write_text(json.dumps(report.suggested_thresholds(), indent=2), "utf-8")
    sys.stdout.write(report.markdown())
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
