"""`vethuq index ...` commands for running OCR indexing on pending sources."""

from __future__ import annotations

from pathlib import Path

import typer
from vethuq_core.db import connect
from vethuq_core.sources import list_sources

app = typer.Typer(help="Run OCR indexing on registered sources.")


@app.command("run")
def run() -> None:
    """Run OCR on new/pending files across every active source.

    A source that's already fully indexed is still checked for files added
    to it since the last run - only genuinely new (or previously failed)
    files are (re)processed; already-indexed files are left untouched. A
    freshly added or reactivated source is (re)processed in full.
    """
    # Imported here, not at module level: vethuq_core.ocr pulls in
    # paddleocr/paddle/cv2, which print import-time noise and are slow to
    # import - other `vethuq` subcommands shouldn't pay that cost just
    # because Typer has to import this module to register `index run`.
    from vethuq_core.ocr import get_document_results, run_ocr

    conn = connect()
    try:
        sources = [s for s in list_sources(conn) if s.status in ("pending", "indexed", "error")]
        if not sources:
            typer.echo("No sources to index.")
            return

        for source in sources:
            typer.echo(f"Indexing {source.source_type}: {source.path} ...")
            processed = run_ocr(conn, source, only_new_files=source.status != "pending")
            if not processed:
                typer.echo("  -> up to date, no new files")
                continue

            results_by_path = {doc.file_path: doc for doc in get_document_results(conn, source.id)}
            for file_path in processed:
                doc = results_by_path[file_path]
                name = Path(doc.file_path).name
                if doc.status == "indexed":
                    typer.echo(f"  -> {name}: indexed | confidence: {doc.confidence:.0%}")
                elif doc.status == "error":
                    typer.echo(f"  -> {name}: error | {doc.error_message}")
                else:
                    typer.echo(f"  -> {name}: {doc.status}")
    finally:
        conn.close()
