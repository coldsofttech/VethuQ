"""Telling which language a scanned file is in, and reading it in the others."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import select

import vethuq
from tests import fake_pipeline as fp
from tests import fake_tiers as ft
from tests.language_addons import TELUGU, LanguageAddonFactory
from vethuq import errors
from vethuq._db import _DocumentLanguage, _PdfPage, _PdfPageQuick
from vethuq._db.values import _PassSource, _PassStatus
from vethuq._indexing import _Indexer
from vethuq._ocr import _Assessment, _LanguageDetector, _Scripts
from vethuq.enums import IndexRunStatus
from vethuq_addon_api import JobState, LanguageSpec
from vethuq_addon_api.testing import FakeExecutor

LATIN = ((0x41, 0x5A), (0x61, 0x7A))
TELUGU_RANGE = ((0x0C00, 0x0C7F),)
EN = LanguageSpec("en", "English", default=True, script_ranges=LATIN)
TE = LanguageSpec("te", "Telugu", script_ranges=TELUGU_RANGE)
TELUGU_TEXT = "తెలుగు పాఠ్యం ఇక్కడ ఉంది"
GARBAGE = "xq zvk wjy plm qrt"


class TestScripts:
    def test_letters_in_a_script(self):
        assert _Scripts.own_share("abc తెలుగు 123", EN) == (9, 3)
        assert _Scripts.own_share("abc తెలుగు 123", TE) == (9, 6)

    def test_a_language_with_no_ranges_owns_all_its_letters(self):
        assert _Scripts.own_share("abc తె", LanguageSpec("xx", "X")) == (5, 5)

    def test_the_languages_a_text_contains(self):
        assert _Scripts.present("hello తెలుగు", [EN, TE]) == ["en", "te"]
        assert _Scripts.present("hello", [EN, TE]) == ["en"]
        assert _Scripts.present("12345 !!!", [EN, TE]) == []
        assert _Scripts.present("hello", [LanguageSpec("xx", "X")]) == []


class TestAssess:
    def test_a_file_with_no_scanned_pages_is_native(self):
        assert _LanguageDetector.assess([(False, "text", 1.0)], EN).verdict == "native"

    def test_too_little_text_is_empty(self):
        assert _LanguageDetector.assess([(True, "hi", 0.9)], EN).verdict == "empty"

    def test_confident_and_in_its_own_script(self):
        result = _LanguageDetector.assess([(True, "a long enough line of text", 0.95)], EN)
        assert isinstance(result, _Assessment) and result.verdict == "confident"
        assert result.script_share == 1.0 and result.letters == 21

    def test_not_confident(self):
        result = _LanguageDetector.assess([(True, "a long enough line of text", 0.5)], EN)
        assert result.verdict == "unsure"

    def test_confident_but_in_another_script(self):
        result = _LanguageDetector.assess([(True, TELUGU_TEXT, 0.95)], EN)
        assert result.verdict == "unsure" and result.script_share == 0.0

    def test_pages_are_weighted_by_their_letters(self):
        pages = [(True, "a" * 100, 0.95), (True, "b" * 10, 0.1)]
        assert _LanguageDetector.assess(pages, EN).verdict == "confident"  # 0.87 overall

    def test_a_page_that_was_not_scanned_says_nothing(self):
        pages = [(False, "x" * 500, 0.1), (True, "a long enough line of text", 0.95)]
        assert _LanguageDetector.assess(pages, EN).verdict == "confident"


class TestBelievableLines:
    @pytest.mark.parametrize(
        ("text", "score", "kept"),
        [
            ("a fine line", 0.9, True),
            ("a fine line", 0.5, False),
            (TELUGU_TEXT, 0.9, False),  # not in English's script
            ("12345", 0.9, True),  # no letters: needs more
            ("12345", 0.8, False),
            ("mostly english with ఒక", 0.9, True),
        ],
    )
    def test_keep_line(self, text, score, kept):
        assert _LanguageDetector.keep_line(text, score, EN) is kept

    def test_believable(self):
        lines = [("good line", 0.9), ("", 0.9), (TELUGU_TEXT, 0.9), ("weak", 0.2)]
        assert _LanguageDetector.believable(lines, EN) == [("good line", 0.9)]


# ----- the whole thing, with the fake pipeline ---------------------------------------------------


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 3600.0)


@pytest.fixture
def telugu(tmp_path_factory, monkeypatch):
    """Telugu installed, with its script."""
    folder = tmp_path_factory.mktemp("telugu")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    module = LanguageAddonFactory.install(
        folder, "telugu", [{**TELUGU, "script_ranges": TELUGU_RANGE}]
    )
    yield
    LanguageAddonFactory.forget(module)


@pytest.fixture
def client(telugu, tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


def scan_in_telugu(confidence_in_english=0.4, in_telugu=0.9, tag=""):
    """A scan whose English read is garbage and whose Telugu read is good."""
    page = fp.scanned_page(f"{GARBAGE}{tag}", confidence=confidence_in_english)
    return fp.in_languages(page, te=(f"{TELUGU_TEXT}{tag}", in_telugu))


def passes(client):
    with client._db().session() as session:
        return {
            (row.language_id, row.status.value, row.source.value, row.position)
            for row in session.scalars(select(_DocumentLanguage))
        }


def text(client, number=1):
    with client._db().session() as session:
        return next(p.text for p in session.scalars(select(_PdfPage)) if p.page_number == number)


def pass_for(client, code):
    with client._db().session() as session:
        language_id = session.scalar(select(_Language.id).where(_Language.language == code))
        return session.get(_DocumentLanguage, (1, language_id))


from vethuq._db import _Language  # noqa: E402


class TestOneLanguage:
    def test_one_candidate_is_read_directly_and_nothing_is_judged(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        client.index.run()
        assert text(client) == GARBAGE  # English, however badly: it is the only candidate
        assert {call[0] for call in fp.STATE.ocr_calls} == {"en"}


class TestConfident:
    def test_the_other_languages_are_skipped(self, client, root):
        write(root, "a.pdf", fp.scanned_page("a long enough line of english text", confidence=0.95))
        client.sources.create(root, languages=["en", "te"])
        run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED
        assert {call[0] for call in fp.STATE.ocr_calls} == {"en"}
        assert pass_for(client, "en").status is _PassStatus.DONE
        te = pass_for(client, "te")
        assert (te.status, te.source) == (_PassStatus.SKIPPED, _PassSource.AUTO)
        assert run.credits_charged == 1.0

    def test_a_blank_scan_settles_on_the_first_language(self, client, root):
        write(root, "a.pdf", fp.scanned_page("hi", confidence=0.2))
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        assert pass_for(client, "te").status is _PassStatus.SKIPPED
        assert {call[0] for call in fp.STATE.ocr_calls} == {"en"}


class TestUnsure:
    def test_the_other_language_reads_the_file_and_the_garbage_is_dropped(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED
        assert [call[0] for call in fp.STATE.ocr_calls] == ["en", "te"]
        assert text(client) == TELUGU_TEXT  # English's unbelievable line never reached the index
        assert pass_for(client, "en").status is _PassStatus.DONE
        te = pass_for(client, "te")
        assert (te.status, te.source, te.position) == (_PassStatus.DONE, _PassSource.AUTO, 1)
        assert te.confidence == pytest.approx(0.9)

    def test_the_second_read_is_an_additional_language_charge(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        run = client.index.run()
        assert run.credits_charged == 2.0  # quick, then the language pass at the same rate
        assert run.ocr_pages == 1  # still one page of the run

    def test_a_search_by_language_finds_it(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        found = client.search.run("తెలుగు", languages=["te"]).matches
        assert [m.file_name for m in found] == ["a.pdf"]

    def test_both_languages_stay_when_both_read_something_believable(self, client, root):
        page = fp.in_languages(
            fp.scanned_page("english words here", confidence=0.7), te=(TELUGU_TEXT, 0.9)
        )
        write(root, "a.pdf", page)
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        assert text(client) == f"english words here\n{TELUGU_TEXT}"
        with client._db().session() as session:
            assert len(session.scalars(select(_PdfPageQuick)).all()) == 2  # read in two languages

    def test_a_line_the_second_language_made_up_is_dropped(self, client, root):
        page = fp.in_languages(scan_in_telugu(), te=(f"{TELUGU_TEXT}\nweak line", 0.55))
        write(root, "a.pdf", page)
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        assert text(client) == ""  # nothing either language read was believable

    def test_a_second_run_does_not_read_it_again(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        fp.STATE.ocr_calls.clear()
        assert client.index.run().credits_charged == 0 and fp.STATE.ocr_calls == []

    def test_quick_goes_first_then_the_passes_for_every_file(self, client, root):
        write(root, "a.pdf", scan_in_telugu(tag=" a"))
        write(root, "b.pdf", scan_in_telugu(tag=" b"))
        client.sources.create(root, languages=["en", "te"])
        client.index.run()
        order = [call[0] for call in fp.STATE.ocr_calls]
        assert order == ["en", "en", "te", "te"]  # both files' first reads before either pass

    def test_a_pass_that_cannot_be_paid_for_waits_for_the_next_run(self, client, root):
        client._credit_engine().policy = lambda: {
            "wallets": {"local": {"daily": 1, "starter": 0}},
            "grace_percent": 0,
        }
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        run = client.index.run()
        assert run.status is IndexRunStatus.WAITING_CREDITS
        assert pass_for(client, "te").status is _PassStatus.PENDING  # still queued
        assert text(client) == ""  # English's unbelievable line is already out of the index


class TestARunsLanguages:
    def test_languages_on_the_run_override_the_source(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)  # no languages of its own
        client.index.run(languages=["en", "te"])
        assert text(client) == TELUGU_TEXT

    def test_a_string_of_ids_is_accepted(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        client.index.run(languages="en, te")
        assert text(client) == TELUGU_TEXT

    def test_the_default_language_goes_first_whatever_the_order(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        client.index.run(languages=["te", "en"])
        assert [call[0] for call in fp.STATE.ocr_calls][0] == "en"

    def test_without_english_the_first_given_reads_first(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        client.index.run(languages=["te"])
        assert {call[0] for call in fp.STATE.ocr_calls} == {"te"}
        assert text(client) == TELUGU_TEXT

    def test_a_language_that_cannot_be_used_is_refused_up_front(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        with pytest.raises(errors.LanguageUnavailableError):
            client.index.run(languages=["en", "xx"])
        assert fp.STATE.ocr_calls == []

    def test_a_bad_value(self, client):
        with pytest.raises(TypeError):
            client.index.run(languages=3)

    def test_reindex_file_in_another_language(self, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root)
        client.index.run()
        assert text(client) == GARBAGE
        client.index.reindex_file(root / "a.pdf", languages=["te"])
        assert text(client) == TELUGU_TEXT


class TestATextLayer:
    def test_a_native_page_is_in_the_languages_its_text_is_written_in(self, client, root):
        write(root, "a.pdf", fp.native_page(f"plenty of native text here and {TELUGU_TEXT} too"))
        client.sources.create(root)
        client.index.run()
        assert pass_for(client, "te").status is _PassStatus.DONE
        assert [m.file_name for m in client.search.run("tex", languages=["te"]).matches] == [
            "a.pdf"
        ]

    def test_an_english_page_gets_no_extra_language(self, client, root):
        write(root, "a.pdf", fp.native_page("plenty of native english text on this page"))
        client.sources.create(root)
        client.index.run()
        assert len(passes(client)) == 1

    def test_with_several_candidates_the_scripts_say_which(self, client, root):
        write(root, "a.pdf", fp.native_page(f"plenty of native text and {TELUGU_TEXT}"))
        write(root, "b.pdf", fp.native_page("plenty of english native text only on b"))
        source = client.sources.create(root, languages=["en", "te"])
        client.index.run()
        with client._db().session() as session:
            rows = {
                (row.document_id, row.language_id): row.status.value
                for row in session.scalars(select(_DocumentLanguage))
            }
        assert fp.STATE.ocr_calls == [] and source.id
        assert sorted(rows.values()).count("done") >= 3  # a: en and te, b: en
        assert "skipped" in rows.values()  # b: not in Telugu


class TestOnARemoteTier:
    @pytest.fixture
    def remote(self, tmp_path_factory, monkeypatch):
        ft.reset()
        folder = tmp_path_factory.mktemp("remote_addon")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        ft.install(folder)

        class ByLanguage(FakeExecutor):
            def _read(self, request):
                result = super()._read(request)
                seen = {"en": (GARBAGE, 0.4), "te": (TELUGU_TEXT, 0.9)}
                text, confidence = seen[request.language.id]
                return type(result)(
                    text=text, confidence=confidence, engine=result.engine,
                    language=request.language.id,
                    lines=tuple((line, confidence) for line in text.splitlines()),
                )  # fmt: skip

        ft.STATE.github_executor = ByLanguage(asynchronous=True, state=JobState.DONE)
        yield ft.STATE.github_executor
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
            del sys.modules[name]

    def test_the_detection_and_the_pass_both_run_remotely(self, remote, client, root):
        write(root, "a.pdf", scan_in_telugu())
        client.sources.create(root, languages=["en", "te"])
        client.index.run(tier="github")  # the English read goes and comes back: unsure
        assert [r.language.id for r in remote.seen] == ["en"]
        assert pass_for(client, "te").status is _PassStatus.PENDING
        client.index.run(tier="github")  # now the Telugu pass goes
        assert [r.language.id for r in remote.seen] == ["en", "te"]
        assert {r.phase for r in remote.seen} == {"quick"}
        assert text(client) == TELUGU_TEXT
        assert pass_for(client, "te").status is _PassStatus.DONE


class TestRotatedReadsInAnotherLanguage:
    @pytest.fixture
    def moderate(self, tmp_path_factory, monkeypatch):
        folder = tmp_path_factory.mktemp("moderate_addon")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        fp.install(folder, {"ocr-moderate": fp.DEEPER["ocr-moderate"]})
        yield
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
            if name.rsplit(".", 1)[-1] == "ocr_moderate":
                del sys.modules[name]

    def test_a_line_not_in_the_languages_script_is_dropped(self, moderate, client, root):
        page = fp.at_angles(
            fp.in_languages(fp.scanned_page("x", confidence=0.9), te=(TELUGU_TEXT, 0.9)),
            a90="english noise from a rotated read\nకొత్త వాక్యం ఇక్కడ",
        )
        write(root, "a.pdf", page)
        client.sources.create(root, languages=["te"])
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert text(client) == f"{TELUGU_TEXT}\nకొత్త వాక్యం ఇక్కడ"

    def test_an_english_only_page_is_read_as_it_always_was(self, moderate, client, root):
        write(root, "a.pdf", fp.at_angles(fp.scanned_page("upright words"), a90="rotated words"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert text(client) == "upright words\nrotated words"
