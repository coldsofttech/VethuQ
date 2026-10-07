from types import SimpleNamespace as NS

import pytest
from vethuq_core.sorting import Sorting

ASC, DESC = Sorting.Order.ASC, Sorting.Order.DESC


def _hit(path, page=None, score=None, engine="like"):
    return NS(file_path=path, page_number=page, score=score, engine=engine)


class TestApply:
    def test_leaves_the_order_alone_without_a_choice(self):
        items = [3, 1, 2]

        assert Sorting.apply(items, {"v": lambda i: i}, None, None) == [3, 1, 2]

    def test_order_alone_sorts_by_the_first_key(self):
        keys = {"a": lambda i: i[0], "b": lambda i: i[1]}

        assert Sorting.apply([(2, 0), (1, 9)], keys, None, ASC) == [(1, 9), (2, 0)]
        assert Sorting.apply([(1, 9), (2, 0)], keys, None, DESC) == [(2, 0), (1, 9)]

    def test_sort_by_alone_is_ascending(self):
        keys = {"a": lambda i: i[0], "b": lambda i: i[1]}

        assert Sorting.apply([(1, 9), (2, 0)], keys, "b", None) == [(2, 0), (1, 9)]

    def test_text_ignores_case(self):
        assert Sorting.apply(["b", "A", "c"], {"v": lambda i: i}, "v", ASC) == ["A", "b", "c"]

    def test_missing_values_come_last_either_way(self):
        keys = {"v": lambda i: i}

        assert Sorting.apply([2, None, 1], keys, "v", ASC) == [1, 2, None]
        assert Sorting.apply([2, None, 1], keys, "v", DESC) == [2, 1, None]

    def test_ties_keep_their_order(self):
        keys = {"v": lambda i: i[0]}
        items = [(1, "a"), (1, "b"), (0, "c")]

        assert Sorting.apply(items, keys, "v", ASC) == [(0, "c"), (1, "a"), (1, "b")]
        assert Sorting.apply(items, keys, "v", DESC) == [(1, "a"), (1, "b"), (0, "c")]

    def test_unicode_text_sorts(self):
        assert Sorting.apply(["Éa", "ab", "Привет"], {"v": lambda i: i}, "v", ASC) == [
            "ab",
            "Éa",
            "Привет",
        ]


class TestSearchResults:
    def test_by_file_then_page(self):
        hits = [_hit("/b.pdf", 1), _hit("/A.pdf", 2), _hit("/A.pdf", 1)]

        ordered = Sorting.search_results(hits, Sorting.SearchBy.FILE, ASC)

        assert [(h.file_path, h.page_number) for h in ordered] == [
            ("/A.pdf", 1),
            ("/A.pdf", 2),
            ("/b.pdf", 1),
        ]

    def test_by_score_descending_puts_unscored_last(self):
        hits = [_hit("/a", score=None), _hit("/b", score=0.2), _hit("/c", score=0.9)]

        ordered = Sorting.search_results(hits, Sorting.SearchBy.SCORE, DESC)

        assert [h.file_path for h in ordered] == ["/c", "/b", "/a"]

    def test_by_page_and_engine(self):
        hits = [_hit("/a", 3, engine="fuzzy"), _hit("/b", 1, engine="exact")]

        assert [
            h.page_number for h in Sorting.search_results(hits, Sorting.SearchBy.PAGE, ASC)
        ] == [
            1,
            3,
        ]
        assert [h.engine for h in Sorting.search_results(hits, Sorting.SearchBy.ENGINE, ASC)] == [
            "exact",
            "fuzzy",
        ]

    def test_unsorted_keeps_the_ranking(self):
        hits = [_hit("/b"), _hit("/a")]

        assert Sorting.search_results(hits, None, None) == hits


class TestOtherLists:
    def test_jobs(self):
        jobs = [
            NS(id=1, status="queued", mode="run", target=None, requested_at="2026-01-02"),
            NS(id=2, status="failed", mode="restart", target="5", requested_at="2026-01-01"),
        ]

        assert [j.id for j in Sorting.jobs(jobs, Sorting.JobBy.QUEUED, ASC)] == [2, 1]
        assert [j.id for j in Sorting.jobs(jobs, Sorting.JobBy.STATUS, ASC)] == [2, 1]
        assert [j.id for j in Sorting.jobs(jobs, Sorting.JobBy.KIND, DESC)] == [1, 2]
        assert [j.id for j in Sorting.jobs(jobs, Sorting.JobBy.TARGET, ASC)] == [2, 1]
        assert [j.id for j in Sorting.jobs(jobs, None, DESC)] == [2, 1]

    def test_runs(self):
        runs = [
            NS(id=1, started_at="2026-01-02", mode="run", target=None, status="completed"),
            NS(id=2, started_at="2026-01-01", mode="restart", target="3", status="failed"),
        ]

        assert [r.id for r in Sorting.runs(runs, Sorting.RunBy.STARTED, ASC)] == [2, 1]
        assert [r.id for r in Sorting.runs(runs, Sorting.RunBy.STATUS, ASC)] == [1, 2]
        assert [r.id for r in Sorting.runs(runs, Sorting.RunBy.ID, DESC)] == [2, 1]

    def test_files_put_missing_confidence_last(self):
        files = [
            NS(file_path="/b", status="indexed", confidence=None, duration=1.0),
            NS(file_path="/a", status="error", confidence=0.5, duration=None),
        ]

        assert [f.file_path for f in Sorting.files(files, Sorting.FileBy.CONFIDENCE, ASC)] == [
            "/a",
            "/b",
        ]
        assert [f.file_path for f in Sorting.files(files, Sorting.FileBy.DURATION, DESC)] == [
            "/b",
            "/a",
        ]
        assert [f.file_path for f in Sorting.files(files, Sorting.FileBy.FILE, ASC)] == ["/a", "/b"]

    def test_catalog(self):
        entries = [NS(label="PDF", extra="type-pdf", ok="b"), NS(label="EML", extra="a", ok="a")]

        def status(entry):
            return entry.ok

        assert [e.label for e in Sorting.catalog(entries, status, Sorting.CatalogBy.NAME, ASC)] == [
            "EML",
            "PDF",
        ]
        assert [
            e.label for e in Sorting.catalog(entries, status, Sorting.CatalogBy.PACKAGE, ASC)
        ] == [
            "EML",
            "PDF",
        ]
        assert [
            e.label for e in Sorting.catalog(entries, status, Sorting.CatalogBy.STATUS, DESC)
        ] == [
            "PDF",
            "EML",
        ]

    def test_models(self):
        models = [
            NS(name="b", size_bytes=1, present=True),
            NS(name="a", size_bytes=9, present=False),
        ]

        assert [m.name for m in Sorting.models(models, Sorting.ModelBy.MODEL, ASC)] == ["a", "b"]
        assert [m.name for m in Sorting.models(models, Sorting.ModelBy.SIZE, DESC)] == ["a", "b"]
        assert [m.name for m in Sorting.models(models, Sorting.ModelBy.STATUS, ASC)] == ["a", "b"]


@pytest.mark.parametrize("enum", [Sorting.Order, Sorting.SearchBy, Sorting.JobBy, Sorting.RunBy])
def test_values_are_the_cli_choices(enum):
    assert all(member.value == member.value.lower() for member in enum)
