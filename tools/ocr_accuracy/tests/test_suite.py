import json

import numpy as np
import pytest

from tools.ocr_accuracy import pages, suite
from tools.ocr_accuracy.engines import ClientReader
from tools.ocr_accuracy.suite import Reading

pytestmark = pytest.mark.usefixtures("font")

LIMITS = {
    "version": 1,
    "provisional": False,
    "limits": {"quick": {"clean": {"max_cer": 0.02, "min_word_recall": 0.95}}},
}


@pytest.fixture
def font():
    try:
        pages.find_font("en")
    except pages.FontNotFound:
        pytest.skip("no English font on this machine")


class Perfect:
    """Reads back the reference of whichever page it is asked about (matched by the image)."""

    def __init__(self):
        self.pages = {}

    def read(self, image, phase, language):
        for page_type in pages.PAGE_TYPES:
            page = self.pages.setdefault(page_type, pages.make(page_type, language))
            if np.array_equal(page.image, image):
                return Reading(page.reference, 0.99)
        raise AssertionError("unknown page")


class Fixed:
    def __init__(self, text="", confidence=0.5, error=None):
        self.text, self.confidence, self.error = text, confidence, error
        self.calls = []

    def read(self, image, phase, language):
        self.calls.append((image.shape, phase, language))
        if self.error:
            raise self.error
        return Reading(self.text, self.confidence)


def test_a_perfect_read_passes():
    report = suite.run(Perfect(), ["quick"], ["en"], ["clean"], LIMITS)
    (result,) = report.results
    assert result.status == suite.PASS and result.cer == 0.0 and result.word_recall == 1.0
    assert result.confidence == 0.99 and result.limits == {"max_cer": 0.02, "min_word_recall": 0.95}
    assert not report.failed


def test_a_bad_read_fails():
    report = suite.run(Fixed("garbage"), ["quick"], ["en"], ["clean"], LIMITS)
    assert [r.status for r in report.results] == [suite.FAIL] and report.failed


def test_no_limit_means_unchecked():
    report = suite.run(Fixed("garbage"), ["deep"], ["en"], ["clean"], LIMITS)
    assert report.results[0].status == suite.UNCHECKED and not report.failed


def test_a_read_that_raises_is_a_failure_with_the_reason():
    report = suite.run(Fixed(error=MemoryError("out of memory")), ["quick"], ["en"], ["large"], {})
    (result,) = report.results
    assert result.status == suite.FAIL and "MemoryError: out of memory" in result.note
    assert result.cer is None


def test_a_missing_font_skips_the_case(monkeypatch):
    monkeypatch.setattr(pages, "FONTS", {"en": []})
    monkeypatch.delenv("VETHUQ_ACCURACY_FONT_EN", raising=False)
    reader = Fixed()
    (result,) = suite.run(reader, ["quick"], ["en"], ["clean"], LIMITS).results
    assert result.status == suite.SKIPPED and reader.calls == []


def test_every_combination_is_run_in_order():
    report = suite.run(Fixed("x"), ["quick", "deep"], ["en"], ["clean", "scan"], {})
    assert [(r.phase, r.page_type) for r in report.results] == [
        ("quick", "clean"),
        ("quick", "scan"),
        ("deep", "clean"),
        ("deep", "scan"),
    ]


def test_the_clock_and_memory_are_recorded():
    ticks = iter([10.0, 12.5])
    (result,) = (
        suite.run_case(
            Fixed("x"), "quick", "en", "clean", {}, clock=lambda: next(ticks), rss=lambda: 321.0
        ),
    )
    assert result.seconds == 2.5 and result.peak_rss_mb == 321.0


def test_judge():
    assert suite.judge(0.0, 1.0, {}) == suite.UNCHECKED
    assert suite.judge(0.01, 0.96, {"max_cer": 0.02, "min_word_recall": 0.95}) == suite.PASS
    assert suite.judge(0.03, 0.96, {"max_cer": 0.02, "min_word_recall": 0.95}) == suite.FAIL
    assert suite.judge(0.01, 0.90, {"max_cer": 0.02, "min_word_recall": 0.95}) == suite.FAIL


def test_the_report_is_json_and_a_table():
    report = suite.run(Perfect(), ["quick"], ["en"], ["clean", "scan"], LIMITS)
    data = report.to_dict()
    assert json.loads(json.dumps(data))["summary"] == {
        "pass": 1,
        "fail": 0,
        "unchecked": 1,
        "skipped": 0,
    }
    table = report.markdown()
    assert "| quick | en | clean | pass |" in table and "| quick | en | scan | unchecked |" in table


def test_provisional_limits_are_flagged_in_the_report():
    report = suite.run(Fixed("x"), ["quick"], ["en"], ["clean"], {**LIMITS, "provisional": True})
    assert report.to_dict()["thresholds_provisional"] and "provisional" in report.markdown()


def test_suggested_limits_pass_the_scores_they_came_from():
    reader = Fixed("The quarterly review of the archive")
    first = suite.run(reader, ["quick"], ["en"], ["clean"], {})
    suggestion = first.suggested_thresholds()
    again = suite.run(reader, ["quick"], ["en"], ["clean"], suggestion)
    assert again.results[0].status == suite.PASS and suggestion["provisional"]


def test_the_shipped_thresholds_name_known_phases_and_pages():
    thresholds = suite.load_thresholds()
    assert thresholds["version"] == 1
    for phase, by_page in thresholds["limits"].items():
        assert phase in {"quick", "moderate", "deep"}
        for page_type, limits in by_page.items():
            assert page_type in pages.PAGE_TYPES
            assert 0 <= limits["max_cer"] < 1 and 0 < limits["min_word_recall"] <= 1


class FakeEngine:
    def __init__(self):
        self.angles = []

    def recognize(self, image, angle=0):
        self.angles.append(angle)
        from types import SimpleNamespace

        good = angle == 180
        return SimpleNamespace(
            text="upright" if good else "sideways", confidence=0.9 if good else 0.2
        )


class FakeRuntime:
    def __init__(self):
        from types import SimpleNamespace

        self.engine_ = FakeEngine()
        self._phases = [
            SimpleNamespace(id="deep", order=3, angles=(15,), available=True),
            SimpleNamespace(id="quick", order=1, angles=(0,), available=True),
            SimpleNamespace(id="moderate", order=2, angles=(90, 180, 270), available=True),
        ]

    def phases(self):
        return self._phases

    def engine(self, language, phase):
        return self.engine_, None


def reader_for(runtime):
    from types import SimpleNamespace

    reader = ClientReader.__new__(ClientReader)
    reader._runtime = runtime
    reader._manager = SimpleNamespace(
        language_specs=lambda: [SimpleNamespace(id="en", available=True)]
    )
    return reader


def test_the_real_reader_lists_phases_in_order_and_reads_the_angles_so_far():
    runtime = FakeRuntime()
    reader = reader_for(runtime)
    assert reader.phases() == ["quick", "moderate", "deep"]
    assert reader._angles("quick") == [0]
    assert reader._angles("moderate") == [0, 90, 180, 270]
    reading = reader.read(np.zeros((2, 2, 3), np.uint8), "moderate", "en")
    assert runtime.engine_.angles == [0, 90, 180, 270]
    assert (reading.text, reading.confidence) == ("upright", 0.9)


def test_the_real_reader_refuses_a_language_that_is_not_there():
    with pytest.raises(LookupError, match="'fr'"):
        reader_for(FakeRuntime()).read(np.zeros((2, 2, 3), np.uint8), "quick", "fr")


class TestCommandLine:
    def run(self, monkeypatch, tmp_path, text, *args):
        import contextlib

        from tools.ocr_accuracy import __main__ as cli

        class FakeClient(contextlib.AbstractContextManager):
            def __init__(self, **kwargs):
                pass

            def __exit__(self, *exc):
                return None

        class FakeReader(Fixed):
            def __init__(self, client):
                super().__init__(text)

            def phases(self):
                return ["quick"]

        monkeypatch.setattr(cli.vethuq, "VethuQ", FakeClient)
        monkeypatch.setattr(cli, "ClientReader", FakeReader)
        return cli.main(["--pages", "clean", *args])

    def test_a_failing_case_exits_1_and_writes_the_outputs(self, monkeypatch, tmp_path, capsys):
        out, summary, suggest = (tmp_path / n for n in ("r.json", "s.md", "g.json"))
        code = self.run(
            monkeypatch, tmp_path, "garbage",
            "--out", str(out), "--summary", str(summary), "--suggest", str(suggest),
        )  # fmt: skip
        assert code == 1
        assert json.loads(out.read_text())["summary"]["fail"] == 1
        assert "| quick | en | clean | fail |" in summary.read_text()
        assert json.loads(suggest.read_text())["limits"]["quick"]["clean"]
        assert "OCR accuracy" in capsys.readouterr().out

    def test_a_pass_exits_0(self, monkeypatch, tmp_path):
        reference = pages.make("clean").reference
        assert self.run(monkeypatch, tmp_path, reference) == 0

    def test_an_unknown_page_type_is_a_usage_error(self, monkeypatch, tmp_path):
        from tools.ocr_accuracy import __main__ as cli

        with pytest.raises(SystemExit) as stop:
            cli.main(["--pages", "nonsense"])
        assert stop.value.code == 2
