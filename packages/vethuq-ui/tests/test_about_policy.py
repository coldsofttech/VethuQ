import pytest
from vethuq_core.policy import PolicyService

pytest.importorskip("tkinter")

from vethuq_ui.windows.settings.about import AboutWindow  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_policy_service(tmp_path, monkeypatch):
    from vethuq_core.paths import Paths

    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
    PolicyService.reset()
    yield
    PolicyService.reset()


def test_about_reports_the_baseline_before_any_policy_is_fetched():
    assert AboutWindow.policy_summary() == "built-in baseline"


def test_about_never_fails_because_of_the_policy(monkeypatch):
    def boom(logger=None):
        raise RuntimeError("broken")

    monkeypatch.setattr(PolicyService, "current", staticmethod(boom))

    assert AboutWindow.policy_summary() == "unavailable"
