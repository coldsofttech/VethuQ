from __future__ import annotations

import pytest

from vethuq_addon_api import (
    Addon,
    JobState,
    LanguageSpec,
    Manifest,
    OcrRequest,
    TierSpec,
)
from vethuq_addon_api.testing import FakeExecutor, FakeHost

EN = LanguageSpec("en", "English", default=True)


def request(key="p1", **kw):
    return OcrRequest(key, "image", EN, **kw)


class TestRequest:
    def test_defaults(self):
        r = request()
        assert (r.phase, r.size_factor, r.language) == ("quick", 1.0, EN)


class TestSynchronous:
    def test_recognize_returns_the_text_for_the_key(self):
        executor = FakeExecutor({"p1": "hello\nworld"}, confidence=0.7)
        result = executor.recognize(request("p1"))
        assert (result.text, result.confidence, result.language) == ("hello\nworld", 0.7, "en")
        assert result.lines == (("hello", 0.7), ("world", 0.7))
        assert executor.recognize(request("other")).confidence == 0.0
        assert [r.key for r in executor.seen] == ["p1", "other"]
        assert not executor.asynchronous and executor.describe() == "a test executor"

    def test_the_asynchronous_methods_are_not_there(self):
        executor = FakeExecutor()
        with pytest.raises(NotImplementedError, match="synchronous"):
            executor.submit([request()])
        with pytest.raises(NotImplementedError, match="synchronous"):
            executor.poll("x")
        with pytest.raises(NotImplementedError, match="synchronous"):
            executor.collect("x")
        with pytest.raises(NotImplementedError, match="synchronous"):
            executor.cancel("x")


class TestAsynchronous:
    def test_a_batch_is_submitted_polled_and_collected(self):
        executor = FakeExecutor({"a": "one", "b": "two"}, asynchronous=True)
        handle = executor.submit([request("a"), request("b")])
        assert executor.poll(handle) is JobState.DONE
        assert {k: r.text for k, r in executor.collect(handle).items()} == {"a": "one", "b": "two"}
        executor.cancel(handle)
        assert executor.cancelled == [handle]
        assert handle != executor.submit([request("c")])

    def test_it_can_be_still_running(self):
        executor = FakeExecutor(asynchronous=True, state=JobState.RUNNING)
        assert executor.poll(executor.submit([request()])) is JobState.RUNNING

    def test_recognize_is_not_there(self):
        with pytest.raises(NotImplementedError, match="asynchronous"):
            FakeExecutor(asynchronous=True).recognize(request())

    def test_job_states(self):
        assert [s.value for s in JobState] == ["queued", "running", "done", "failed"]


class TestAddon:
    def test_an_addon_offers_no_tiers_unless_it_says_so(self, tmp_path):
        class Plain(Addon):
            manifest = Manifest("plain", "plain", "1.0.0")

        assert Plain(FakeHost(tmp_path / "db")).processing_tiers() == []

    def test_a_tier_addon(self, tmp_path):
        executor = FakeExecutor(asynchronous=True)

        class Remote(Addon):
            manifest = Manifest("remote", "remote", "1.0.0")

            def processing_tiers(self):
                return [
                    TierSpec("remote", "Remote", "remote", executor, available=False, reason="off")
                ]

        (spec,) = Remote(FakeHost(tmp_path / "db")).processing_tiers()
        assert (spec.id, spec.wallet, spec.available, spec.reason) == (
            "remote",
            "remote",
            False,
            "off",
        )
        assert spec.executor is executor

    def test_the_api_version(self):
        from vethuq_addon_api import API_VERSION

        assert API_VERSION == "0.6.0"
