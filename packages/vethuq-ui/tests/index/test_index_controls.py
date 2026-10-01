from datetime import UTC, datetime
from unittest.mock import patch

from vethuq_core.index import IndexRunner, IndexRunnerError, IndexState
from vethuq_core.source import SourceNotFoundError
from vethuq_ui import index_controls


def _state(status: str) -> IndexState:
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
        current_files=[],
        started_at=now,
        updated_at=now,
    )


class TestIndexControls:
    def test_launch_starts_a_run_when_none_is_active(self, window):
        started = []
        with (
            patch.object(IndexRunner, "is_running", return_value=(False, None)),
            patch.object(IndexRunner, "start_run", lambda **kwargs: started.append(kwargs)),
        ):
            window.index_controls.launch_or_attach()

        assert len(started) == 1

    def test_launch_attaches_to_a_run_already_going(self, window):
        with (
            patch.object(IndexRunner, "is_running", return_value=(True, 99)),
            patch.object(IndexRunner, "start_run") as start,
        ):
            window.index_controls.launch_or_attach()

        start.assert_not_called()

    def test_poll_reports_an_active_run_and_refreshes_the_sources(self, window):
        refreshed = []
        window.index_controls._refresh_sources = lambda: refreshed.append(1)
        with patch.object(IndexRunner, "read_state", return_value=_state("running")):
            window.index_controls.poll()

        assert window.status_bar.var.get().startswith("Indexing (1/4)")
        assert refreshed == [1]
        assert str(window.ribbon.stop_button.cget("state")) == "normal"

    def test_poll_goes_idle_when_there_is_no_active_run(self, window):
        with patch.object(IndexRunner, "read_state", return_value=_state("completed")):
            window.index_controls.poll()

        assert window.status_bar.var.get() == "Idle"
        assert str(window.ribbon.stop_button.cget("state")) == "disabled"

    def test_buttons_follow_the_run_state(self, window):
        window.index_controls.update_buttons(_state("paused"))
        assert str(window.ribbon.pause_resume_button.cget("text")) == "Resume"
        assert str(window.ribbon.pause_resume_button.cget("state")) == "normal"

        window.index_controls.update_buttons(_state("running"))
        assert str(window.ribbon.pause_resume_button.cget("text")) == "Pause"

        window.index_controls.update_buttons(None)
        assert str(window.ribbon.pause_resume_button.cget("state")) == "disabled"
        assert str(window.ribbon.stop_button.cget("state")) == "disabled"

    def test_toggle_pauses_a_running_run_and_resumes_a_paused_one(self, window):
        calls = []
        with (
            patch.object(IndexRunner, "request_pause", lambda **k: calls.append("pause")),
            patch.object(IndexRunner, "request_resume", lambda **k: calls.append("resume")),
        ):
            with patch.object(IndexRunner, "read_state", return_value=_state("running")):
                window.index_controls.toggle_pause_resume()
            with patch.object(IndexRunner, "read_state", return_value=_state("paused")):
                window.index_controls.toggle_pause_resume()

        assert calls == ["pause", "resume"]

    def test_control_errors_are_shown_not_raised(self, window):
        with (
            patch.object(IndexRunner, "signal_stop", side_effect=IndexRunnerError("not running")),
            patch.object(index_controls, "show_error") as error,
        ):
            window.index_controls.stop()

        error.assert_called_once()
        assert error.call_args.args[2] == "not running"

    def test_a_targeted_run_refreshes_the_sources_or_shows_the_error(self, window):
        refreshed = []
        window.index_controls._refresh_sources = lambda: refreshed.append(1)
        with patch.object(IndexRunner, "start_run", lambda *a, **k: 1):
            window.index_controls.start_targeted_run("1", restart=False)
        assert refreshed == [1]

        with (
            patch.object(IndexRunner, "start_run", side_effect=SourceNotFoundError("gone")),
            patch.object(index_controls, "show_error") as error,
        ):
            window.index_controls.start_targeted_run("9", restart=True)
        error.assert_called_once()
        assert refreshed == [1]

    def test_shutdown_signals_stop_and_ends_polling(self, window):
        scheduled = []
        window.index_controls._window = type(
            "W", (), {"after": lambda self, ms, fn: scheduled.append(fn)}
        )()
        with (
            patch.object(IndexRunner, "signal_stop") as stop,
            patch.object(IndexRunner, "read_state", return_value=None),
        ):
            window.index_controls.shutdown()
            window.index_controls.poll()

        stop.assert_called_once()
        assert scheduled == []  # no further poll scheduled once closing
