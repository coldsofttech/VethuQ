from __future__ import annotations

import os
import threading
import time

import pytest
from vethuq_background.host import ServiceHost


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ServiceHost, "POLL_SECONDS", 0.02)
    monkeypatch.setattr(ServiceHost, "CONTROL_SECONDS", 0.02)


def until(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_once_works_what_is_waiting_then_exits(client):
    client.index.queue.submit()
    client.index.queue.submit(mode="restart")
    assert ServiceHost(client).run(once=True) == 2
    assert [j.status.value for j in client.index.queue.list()] == ["completed", "completed"]
    assert client.index.history()[-1].files_processed == 1


def test_the_marker_is_there_while_it_runs_and_gone_after(client):
    host = ServiceHost(client)
    thread = threading.Thread(target=host.run)
    thread.start()
    try:
        assert until(client.index.queue.service_running)
        assert client.index.queue.service_info()["pid"] == os.getpid()
    finally:
        host.stop()
        thread.join(5)
    assert not client.index.queue.service_running()


def test_it_takes_requests_as_they_arrive_and_stops_on_stop(client):
    host = ServiceHost(client)
    thread = threading.Thread(target=host.run)
    thread.start()
    try:
        job = client.index.queue.submit()
        assert until(lambda: not client.index.queue.get(job.id).open)
        assert client.index.queue.get(job.id).status.value == "completed"
    finally:
        host.stop()
        thread.join(5)
    assert not thread.is_alive() and host.worked == 1


def test_pause_takes_no_request_until_resume(client):
    control = client.index.queue.control_file()
    control.write_text("pause")
    host = ServiceHost(client)
    thread = threading.Thread(target=host.run)
    thread.start()
    try:
        job = client.index.queue.submit()
        assert until(lambda: host.paused)
        time.sleep(0.2)
        assert client.index.queue.get(job.id).status.value == "queued"
        control.write_text("run")
        assert until(lambda: client.index.queue.get(job.id).status.value == "completed")
        assert not host.paused
    finally:
        host.stop()
        thread.join(5)


def test_a_bad_request_does_not_stop_the_service(client):
    bad = client.index.queue.submit(999)
    good = client.index.queue.submit()
    assert ServiceHost(client).run(once=True) == 2
    assert client.index.queue.get(bad.id).status.value == "failed"
    assert client.index.queue.get(good.id).status.value == "completed"


def test_control_asked_with_nothing_running_is_harmless(client):
    host = ServiceHost(client)
    host.pause()
    host.resume()
    host.stop()
    assert host.paused is False
