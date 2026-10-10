import logging

import pytest
from vethuq_core.policy import PolicyClient, PolicyService, PolicySource


@pytest.fixture(autouse=True)
def _fresh_service():
    PolicyService.reset()
    yield
    PolicyService.reset()


def test_client_is_shared():
    assert PolicyService.client() is PolicyService.client()


def test_start_returns_a_daemon_thread_and_never_blocks():
    thread = PolicyService.start()
    assert thread is not None and thread.daemon
    thread.join(5)
    assert PolicyService.current().source is PolicySource.BASELINE


def test_start_never_raises(monkeypatch, caplog):
    def boom(self, force=False):
        raise RuntimeError("no threads")

    monkeypatch.setattr(PolicyClient, "refresh_in_background", boom)
    with caplog.at_level(logging.WARNING, logger="vethuq.policy"):
        assert PolicyService.start() is None
    assert "Could not start" in caplog.text


def test_uses_the_logger_it_is_given(tmp_path, monkeypatch):
    logger = logging.getLogger("vethuq.test-policy")
    assert PolicyService.client(logger)._logger is logger
