from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq._credits import _Clock
from vethuq._indexing import _Indexer
from vethuq._stats import _Bands
from vethuq.enums import ConfidenceBand, FileStatus, SortOrder, StatsGroupBy, StatsSortBy
from vethuq.stats import LowConfidencePage, Stats, StatsOverview, StatsRow


class Time:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)

    def next_day(self) -> None:
        self.now = (self.now + timedelta(days=1)).replace(hour=1)


@pytest.fixture
def time(monkeypatch):
    clock = Time()
    monkeypatch.setattr(_Clock, "system", staticmethod(lambda: clock.now))
    return clock


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def client(tmp_path, time):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


def write(folder, name, *pages, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(fp.pdf_document(*pages, **extra), encoding="utf-8")


@pytest.fixture
def two_sources(client, tmp_path, time):
    """Source `a` on day one (a scan at 95%, one at 75%, one native page, a bad file) and source
    `b` on day two (a scan at 50%, a mixed page)."""
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "one.pdf", fp.scanned_page("very sure words", confidence=0.95),
          fp.scanned_page("less sure words", confidence=0.75), fp.native_page())  # fmt: skip
    write(a, "bad.pdf", fp.native_page(), error="corrupt")
    sa = client.sources.create(a)
    client.index.run(sa.id, workers=0)
    time.next_day()
    write(b, "two.pdf", fp.scanned_page("unreliable words", confidence=0.5),
          fp.mixed_page("Native text with enough words in it.", "pic", region_side=400,
                        confidence=0.85))  # fmt: skip
    sb = client.sources.create(b)
    client.index.run(sb.id, workers=0)
    return sa, sb


class TestBands:
    @pytest.mark.parametrize(
        ("confidence", "band"),
        [
            (1.0, "high"),
            (0.90, "high"),
            (0.899, "medium"),
            (0.80, "medium"),
            (0.799, "low"),
            (0.70, "low"),
            (0.699, "unreliable"),
            (0.0, "unreliable"),
        ],
    )
    def test_the_default_cut_offs(self, confidence, band):
        assert _Bands.of(confidence, (70, 80, 90)).value == band

    def test_the_setting(self, client):
        s = client.settings.confidence
        assert s.get_bands() == (70, 80, 90)
        s.set_bands(50, 70, 95)
        assert s.get_bands() == (50, 70, 95)
        s.reset_bands()
        assert s.get_bands() == (70, 80, 90)

    @pytest.mark.parametrize(
        "values",
        [(80, 70, 90), (70, 70, 90), (-1, 80, 90), (70, 80, 101), (70.5, 80, 90), (True, 80, 90)],
    )
    def test_bad_bands(self, client, values):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.confidence.set_bands(*values)

    def test_damaged_values_fall_back(self, client):
        from vethuq._settings import _ConfidenceSettings, _Settings

        with client._db().session() as session:
            _Settings.set(session, _ConfidenceSettings.KEY, "9,5,1")
        assert client.settings.confidence.get_bands() == (70, 80, 90)
        with client._db().session() as session:
            _Settings.set(session, _ConfidenceSettings.KEY, "a,b")
        assert client.settings.confidence.get_bands() == (70, 80, 90)


class TestFileConfidence:
    def test_a_file_shows_its_band_and_its_weak_pages(self, client, two_sources):
        sa, sb = two_sources
        files = {f.name: f.index for f in client.sources.list_files(sa.id, detailed=True)}
        one = files["one.pdf"]
        assert one.pages == 3 and one.confidence == pytest.approx((0.95 + 0.75 + 1.0) / 3)
        assert one.band is ConfidenceBand.HIGH  # 90% on average
        assert one.low_confidence_pages == 1
        assert one.to_dict()["band"] == "high"

    def test_filtering_by_confidence_and_band(self, client, two_sources):
        sa, sb = two_sources
        names = lambda **kw: sorted(  # noqa: E731
            f.name for f in client.sources.list_files(sb.id, detailed=True, **kw)
        )
        assert names() == ["two.pdf"]
        assert names(min_confidence=0.5) == ["two.pdf"]
        assert names(min_confidence=0.99) == []
        assert names(band="unreliable") == ["two.pdf"]  # (0.5 + 0.85) / 2 = 0.675
        assert names(band="medium") == []
        assert names(band=ConfidenceBand.HIGH) == []

    def test_the_filters_need_detail_and_valid_values(self, client, two_sources):
        sa, _ = two_sources
        with pytest.raises(ValueError, match="detailed"):
            client.sources.list_files(sa.id, min_confidence=0.5)
        with pytest.raises(ValueError, match="detailed"):
            client.sources.list_files(sa.id, band="high")
        with pytest.raises(ValueError):
            client.sources.list_files(sa.id, detailed=True, min_confidence=2)
        with pytest.raises(ValueError):
            client.sources.list_files(sa.id, detailed=True, band="nope")


class TestOverview:
    def test_the_default_is_one_row_per_source(self, client, two_sources):
        sa, sb = two_sources
        overview = client.stats.overview()
        assert isinstance(overview, StatsOverview) and isinstance(client.stats, Stats)
        assert overview.group_by is StatsGroupBy.SOURCE
        assert [r.key for r in overview.rows] == [sa.path, sb.path]
        a, b = overview.rows
        assert (a.pages, a.native_pages, a.ocr_pages, a.passes) == (3, 1, 2, 2)
        assert (a.credits, a.files, a.failures) == (2.5, 1, 1)
        assert a.confidence == pytest.approx((0.95 + 0.75 + 1.0) / 3)
        assert a.bands == {"high": 2, "medium": 0, "low": 1, "unreliable": 0}
        assert (b.pages, b.ocr_pages, b.credits) == (2, 2, 1.659)
        assert b.bands == {"high": 0, "medium": 1, "low": 0, "unreliable": 1}

    def test_the_total_adds_everything_up(self, client, two_sources):
        total = client.stats.overview().total
        assert (total.pages, total.ocr_pages, total.native_pages) == (5, 4, 1)
        assert total.credits == 4.159 and total.failures == 1 and total.key == "total"
        assert total.duration_ms >= 0
        assert total.bands == {"high": 2, "medium": 1, "low": 1, "unreliable": 1}

    def test_processing_figures(self, client, two_sources):
        row = client.stats.overview().total
        assert row.passes == 4
        if row.duration_ms:
            assert row.ms_per_ocr_page == pytest.approx(row.duration_ms / row.ocr_pages)
            assert row.pages_per_minute == pytest.approx(row.ocr_pages / (row.duration_ms / 60000))
        else:
            assert row.pages_per_minute is None

    @pytest.mark.parametrize(
        ("group", "keys"),
        [
            ("language", ["en"]),
            ("file_type", ["pdf"]),
            ("engine", ["(none)", "fake-ocr 1.0"]),
            ("page_source", ["mixed", "native", "ocr"]),
            ("band", ["high", "low", "medium", "unreliable"]),
            ("day", ["2026-10-12", "2026-10-13"]),
        ],
    )
    def test_every_grouping(self, client, two_sources, group, keys):
        overview = client.stats.overview(group)
        assert sorted(r.key for r in overview.rows) == keys
        assert sum(r.pages for r in overview.rows) == 5
        assert overview.group_by is StatsGroupBy(group)

    def test_failures_by_day_and_file_type(self, client, two_sources):
        by_day = {r.key: r.failures for r in client.stats.overview("day").rows}
        assert by_day == {"2026-10-12": 1, "2026-10-13": 0}
        assert client.stats.overview("file_type").rows[0].failures == 1
        assert client.stats.overview("language").rows[0].failures is None

    def test_filters(self, client, two_sources):
        sa, sb = two_sources
        stats = client.stats
        assert stats.overview(source=sa.id).total.pages == 3
        assert stats.overview(source=sb.path).total.pages == 2
        assert stats.overview(language="EN").total.pages == 5
        assert stats.overview(language="te").total.pages == 0
        assert stats.overview(file_type="pdf").total.pages == 5
        assert stats.overview(engine="fake-ocr 1.0").total.pages == 4
        assert stats.overview(page_source="native").total.pages == 1
        assert stats.overview(band="unreliable").total.pages == 1
        assert stats.overview(band=ConfidenceBand.HIGH).total.pages == 2
        assert stats.overview(since="2026-10-13").total.pages == 2
        assert stats.overview(until=date(2026, 10, 12)).total.pages == 3
        assert stats.overview(since=datetime(2026, 10, 12, 23), until="2026-10-12").total.pages == 3
        assert stats.overview(source=sa.id, band="low").total.pages == 1

    def test_failures_are_left_out_when_filtering_by_something_they_lack(self, client, two_sources):
        assert client.stats.overview(language="en").total.failures is None
        assert client.stats.overview(file_type="pdf").total.failures == 1

    def test_sorting(self, client, two_sources):
        sa, sb = two_sources
        by = lambda key, **kw: [  # noqa: E731
            r.key for r in client.stats.overview(sort_by=key, **kw).rows
        ]
        assert by(StatsSortBy.KEY) == [sa.path, sb.path]
        assert by(StatsSortBy.KEY, order=SortOrder.DESC) == [sb.path, sa.path]
        assert by("pages", order="desc") == [sa.path, sb.path]
        assert by("pages") == [sb.path, sa.path]
        assert by("credits", order="desc") == [sa.path, sb.path]
        assert by("confidence", order="desc") == [sa.path, sb.path]
        assert by("failures", order="desc") == [sa.path, sb.path]
        assert by("files") == [sb.path, sa.path] or by("files") == [sa.path, sb.path]
        assert by("ocr_pages") == [sa.path, sb.path] or by("ocr_pages") == [sb.path, sa.path]
        assert len(by("duration_ms")) == 2

    def test_paging_and_the_total_still_covers_everything(self, client, two_sources):
        sa, sb = two_sources
        page = client.stats.overview(limit=1)
        assert [r.key for r in page.rows] == [sa.path] and page.total.pages == 5
        assert [r.key for r in client.stats.overview(limit=1, offset=1).rows] == [sb.path]
        assert client.stats.overview(offset=5).rows == []

    def test_bad_arguments(self, client, two_sources):
        for kwargs, error in (
            ({"group_by": "nope"}, ValueError),
            ({"sort_by": "nope"}, ValueError),
            ({"order": "up"}, ValueError),
            ({"band": "nope"}, ValueError),
            ({"page_source": "nope"}, ValueError),
            ({"since": "yesterday"}, ValueError),
            ({"since": 5}, TypeError),
            ({"limit": -1}, ValueError),
            ({"offset": -1}, ValueError),
            ({"source": 999}, errors.SourceNotFoundError),
        ):
            with pytest.raises(error):
                client.stats.overview(**kwargs)

    def test_a_removed_source_is_still_counted(self, client, two_sources):
        sa, _ = two_sources
        client.sources.remove(sa.id)
        assert client.stats.overview(source=sa.id).total.pages == 3
        assert client.stats.source(sa.path).pages == 3

    def test_purging_keeps_the_statistics(self, client, two_sources):
        sa, sb = two_sources
        client.sources.remove(sa.id)
        client.sources.purge(sa.id)
        overview = client.stats.overview()
        assert sorted(r.key for r in overview.rows) == ["(purged source)", sb.path]
        assert overview.total.pages == 5 and overview.total.credits == 4.159
        purged = next(r for r in overview.rows if r.key == "(purged source)")
        assert (purged.pages, purged.files) == (3, None)
        with pytest.raises(errors.SourceNotFoundError):
            client.stats.overview(source=sa.id)

    def test_nothing_yet(self, client):
        overview = client.stats.overview()
        assert overview.rows == [] and overview.total.pages == 0
        assert overview.total.confidence is None and overview.total.pages_per_minute is None

    def test_dict_and_json(self, client, two_sources):
        overview = client.stats.overview()
        assert json.loads(overview.to_json()) == overview.to_dict()
        assert overview.to_dict()["group_by"] == "source"
        row = overview.rows[0]
        assert isinstance(row, StatsRow) and json.loads(row.to_json()) == row.to_dict()

    def test_repeated_runs_add_up(self, client, two_sources, time):
        sa, _ = two_sources
        fp.STATE.flaky.clear()
        folder = sa.path
        write(
            __import__("pathlib").Path(folder),
            "three.pdf",
            fp.scanned_page("another page of words"),
        )
        client.index.run(sa.id)
        assert client.stats.source(sa.id).pages == 4


class TestFailureCodes:
    def test_by_reason(self, client, tmp_path):
        d = tmp_path / "d"
        write(d, "pw.pdf", fp.native_page(), error="password")
        write(d, "corrupt.pdf", fp.native_page(), error="corrupt")
        write(d, "boom.pdf", fp.native_page(), error="boom")
        write(d, "big.pdf", fp.scanned_page(width=9999, height=9999))
        client.sources.create(d)
        fp.STATE.engine_available = True
        client.index.run(workers=0)
        assert client.stats.failures() == {
            "corrupt": 1,
            "other": 1,
            "page_too_large": 1,
            "password": 1,
        }
        assert client.stats.failures(file_type="pdf")["other"] == 1
        assert client.stats.failures(file_type="docx") == {}
        assert client.stats.failures(since="2999-01-01") == {}
        assert client.stats.failures(until="2000-01-01") == {}

    def test_an_unavailable_engine(self, client, tmp_path):
        fp.STATE.engine_available = False
        d = tmp_path / "d"
        write(d, "s.pdf", fp.scanned_page())
        source = client.sources.create(d)
        client.index.run(workers=0)
        assert client.stats.failures(source=source.id) == {"ocr_unavailable": 1}
        row = client.sources.list_files(source.id, detailed=True)[0]
        assert row.index.status is FileStatus.ERROR

    def test_the_error_code_is_kept_on_the_file_until_it_is_indexed(self, client, tmp_path):
        from sqlalchemy import select

        from vethuq._db import _DocumentIndex

        d = tmp_path / "d"
        write(d, "c.pdf", fp.native_page(), error="corrupt")
        client.sources.create(d)
        client.index.run()
        with client._db().session() as session:
            assert session.scalars(select(_DocumentIndex)).one().error_code == "corrupt"


class TestLowConfidencePages:
    def test_the_weak_pages_least_sure_first(self, client, two_sources):
        pages = client.stats.low_confidence_pages()
        assert all(isinstance(p, LowConfidencePage) for p in pages)
        assert [(p.page_number, p.band.value) for p in pages] == [(1, "unreliable"), (2, "low")]
        assert pages[0].path.endswith("two.pdf") and pages[0].read_by == "ocr"
        assert pages[1].path.endswith("one.pdf")

    def test_filters(self, client, two_sources):
        sa, sb = two_sources
        assert len(client.stats.low_confidence_pages(source=sa.id)) == 1
        assert [p.band.value for p in client.stats.low_confidence_pages(band="low")] == ["low"]
        assert len(client.stats.low_confidence_pages(limit=1)) == 1
        assert len(client.stats.low_confidence_pages(limit=None)) == 2

    def test_the_cut_off_follows_the_setting(self, client, two_sources):
        client.settings.confidence.set_bands(10, 20, 30)
        assert client.stats.low_confidence_pages() == []

    def test_dict_and_json(self, client, two_sources):
        page = client.stats.low_confidence_pages()[0]
        assert page.to_dict()["band"] == "unreliable"
        assert json.loads(page.to_json()) == page.to_dict()
