from datetime import UTC, datetime

from vethuq_core.index import IndexState
from vethuq_ui.status_bar import StatusBar


def _state(status: str, *, current: list[str] | None = None) -> IndexState:
    now = datetime.now(UTC).isoformat()
    return IndexState(
        run_id=1,
        pid=1,
        target=None,
        mode="run",
        status=status,
        total_files=4,
        processed_files=1,
        failed_files=0,
        thread_workers_setting="0",
        workers=1,
        current_files=current or [],
        started_at=now,
        updated_at=now,
    )


class TestStatusBar:
    def test_starts_idle(self, root):
        assert StatusBar(root).var.get() == "Idle"

    def test_shows_progress_and_current_file_while_indexing(self, root):
        bar = StatusBar(root)

        bar.set_indexing(_state("running", current=["/docs/a.pdf", "/docs/b.pdf"]))

        assert bar.var.get() == "Indexing (1/4): a.pdf, b.pdf"

    def test_omits_the_file_list_when_none_is_in_flight(self, root):
        bar = StatusBar(root)

        bar.set_indexing(_state("running"))

        assert bar.var.get() == "Indexing (1/4)"

    def test_shows_paused(self, root):
        bar = StatusBar(root)

        bar.set_indexing(_state("paused", current=["/docs/a.pdf"]))

        assert bar.var.get() == "Paused (1/4)"

    def test_set_idle_resets_the_text(self, root):
        bar = StatusBar(root)
        bar.set_indexing(_state("running"))

        bar.set_idle()

        assert bar.var.get() == "Idle"
