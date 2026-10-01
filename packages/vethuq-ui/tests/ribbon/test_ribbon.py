from unittest.mock import MagicMock

from vethuq_core.settings import GpuSettings
from vethuq_ui.ribbon import Ribbon, RibbonActions


def _actions() -> RibbonActions:
    return RibbonActions(
        show_search=MagicMock(),
        add_folder=MagicMock(),
        add_file=MagicMock(),
        show_source_list=MagicMock(),
        toggle_pause_resume=MagicMock(),
        stop=MagicMock(),
        delete_source=MagicMock(),
    )


class TestRibbon:
    def test_pause_and_stop_start_disabled(self, root, conn):
        ribbon = Ribbon(root, conn, _actions())

        assert str(ribbon.pause_resume_button.cget("state")) == "disabled"
        assert str(ribbon.stop_button.cget("state")) == "disabled"

    def test_buttons_call_their_actions(self, root, conn):
        actions = _actions()
        ribbon = Ribbon(root, conn, actions)
        ribbon.pause_resume_button.config(state="normal")
        ribbon.stop_button.config(state="normal")

        ribbon.pause_resume_button.invoke()
        ribbon.stop_button.invoke()
        ribbon.delete_button.invoke()

        actions.toggle_pause_resume.assert_called_once()
        actions.stop.assert_called_once()
        actions.delete_source.assert_called_once()

    def test_delete_button_is_only_shown_when_asked(self, root, conn):
        ribbon = Ribbon(root, conn, _actions())
        ribbon.pack()
        root.update()
        assert not ribbon.delete_button.winfo_ismapped()

        ribbon.set_delete_visible(True)
        root.update()
        assert ribbon.delete_button.winfo_ismapped()

        ribbon.set_delete_visible(False)
        root.update()
        assert not ribbon.delete_button.winfo_ismapped()

    def test_gpu_toggle_persists_the_setting(self, root, conn):
        ribbon = Ribbon(root, conn, _actions())
        assert ribbon.gpu_var.get() is False

        ribbon.gpu_var.set(True)
        ribbon.on_toggle_gpu()

        assert GpuSettings.is_enabled(conn) is True
        assert ribbon.gpu_icon_name() == "gpu"

    def test_gpu_state_is_read_from_the_setting(self, root, conn):
        GpuSettings.set_enabled(conn, True)

        assert Ribbon(root, conn, _actions()).gpu_var.get() is True
