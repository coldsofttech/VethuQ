from __future__ import annotations

import threading
import time

import pytest

from vethuq._indexing.gate import _ContentGate, _Scheduler


class TestContentGate:
    def test_the_same_content_is_handled_one_at_a_time(self):
        gate = _ContentGate()
        inside, overlap = [], []

        def work():
            with gate.hold("same"):
                inside.append(1)
                if len(inside) > 1:
                    overlap.append(1)
                time.sleep(0.02)
                inside.pop()

        threads = [threading.Thread(target=work) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert overlap == []
        assert gate._held == {}  # nothing is kept once everyone is done

    def test_different_content_does_not_wait(self):
        gate = _ContentGate()
        with gate.hold("a"), gate.hold("b"):
            assert set(gate._held) == {"a", "b"}

    def test_it_releases_after_an_error(self):
        gate = _ContentGate()
        with pytest.raises(RuntimeError), gate.hold("a"):
            raise RuntimeError
        with gate.hold("a"):
            pass


class TestScheduler:
    def test_auto_is_between_one_and_the_maximum(self):
        assert 1 <= _Scheduler.auto() <= _Scheduler.MAX_WORKERS

    def test_little_memory_means_one_worker(self, monkeypatch):
        class Memory:
            available = 100

        monkeypatch.setattr("psutil.virtual_memory", lambda: Memory())
        assert _Scheduler.auto() == 1

    def test_many_cores_are_capped(self, monkeypatch):
        class Memory:
            available = 10**12

        monkeypatch.setattr("psutil.virtual_memory", lambda: Memory())
        monkeypatch.setattr("psutil.cpu_count", lambda logical=True: 64)
        assert _Scheduler.auto() == _Scheduler.MAX_WORKERS

    def test_a_request_beats_the_setting(self):
        assert _Scheduler.resolve(3, "auto") == 3
        assert _Scheduler.resolve(0, 5) == 0
        assert _Scheduler.resolve(None, 5) == 5
        assert 1 <= _Scheduler.resolve(None, "auto") <= 8
