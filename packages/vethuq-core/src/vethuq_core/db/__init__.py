"""VethuQ's data-access layer - the only place in the codebase that runs SQL.

Every other module talks to SQLite through the query functions re-exported
here (grouped into submodules by table) rather than importing `sqlite3` or
calling `conn.execute`/`conn.executemany`/`conn.executescript` itself.
`connection` additionally owns the connection/schema/migration lifecycle.
"""

from __future__ import annotations

from vethuq_core.db.connection import (
    Db,
)
from vethuq_core.db.index_runs_queries import (
    end_running_index_run,
    fail_all_running_index_runs,
    fail_index_run,
    insert_index_run,
    list_index_runs,
)
from vethuq_core.db.ocr_phases_queries import (
    complete_document_phase,
    count_documents_short_of_phase,
    count_pages_short_of_phase,
    get_document_index_file_size,
    get_document_phase_completion,
    get_document_phase_work,
    get_page_text_row,
    list_pages_short_of_phase,
    list_phase_progress_rows,
    mark_page_phase_done,
    start_document_phase,
    update_document_phase_work,
    update_page_text,
)

__all__ = [
    "Db",
    "complete_document_phase",
    "count_documents_short_of_phase",
    "count_pages_short_of_phase",
    "end_running_index_run",
    "fail_all_running_index_runs",
    "fail_index_run",
    "get_document_index_file_size",
    "get_document_phase_completion",
    "get_document_phase_work",
    "get_page_text_row",
    "insert_index_run",
    "list_index_runs",
    "list_pages_short_of_phase",
    "list_phase_progress_rows",
    "mark_page_phase_done",
    "start_document_phase",
    "update_document_phase_work",
    "update_page_text",
]
