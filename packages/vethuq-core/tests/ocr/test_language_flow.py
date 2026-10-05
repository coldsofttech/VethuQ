"""Reading a file in more than one language: the first language, doubting it, and the queue."""

import json
from unittest.mock import patch

import pytest
from vethuq_core.ocr import Ocr, Quick
from vethuq_core.ocr.engines import OcrResult
from vethuq_core.ocr.passes import LanguagePasses
from vethuq_core.paths import Paths
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources

ENGLISH = [("Invoice total due", 0.96), ("Museum of art", 0.94)]
JUNK = [("qzxv wplk", 0.31), ("mnbvc lkjh", 0.27), ("rtyuu", 0.22)]
TELUGU = [("తెలుగు పాఠం", 0.93), ("అమ్మ ఇల్లు", 0.91)]


class FakeEngine:
    """An OCR engine that reads whatever lines it was given, whatever the image."""

    name = "fake 1.0"

    def __init__(self, language, lines):
        self.language = language
        self.lines = lines
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        text = "\n".join(text for text, _ in self.lines)
        confidence = sum(score for _, score in self.lines) / len(self.lines) if self.lines else 0.0
        return OcrResult(
            text=text,
            confidence=confidence,
            engine=self.name,
            language=self.language,
            image_width=10,
            image_height=10,
            lines=tuple(self.lines),
        )


@pytest.fixture
def engines():
    return {"en": FakeEngine("en", ENGLISH), "te": FakeEngine("te", TELUGU)}


@pytest.fixture(autouse=True)
def fake_engines(engines):
    with patch(
        "vethuq_core.ocr.engines.Engines.get",
        side_effect=lambda storage, language=None: engines[language or "en"],
    ):
        yield


@pytest.fixture
def source(storage, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "scan.png").write_bytes(b"png bytes")
    return Sources.add(storage, folder)


def _passes(conn):
    return [
        (r["language"], r["position"], r["status"], r["source"])
        for r in conn.execute("SELECT * FROM document_languages ORDER BY position")
    ]


def _page(conn):
    return conn.execute("SELECT * FROM image_pages").fetchone()


class TestEnglishOnly:
    def test_a_single_chosen_language_is_read_directly(self, storage, conn, source, engines):
        OcrSettings.set_languages(storage, "en")

        Quick.run(storage, source)

        assert engines["en"].calls == 1
        assert engines["te"].calls == 0
        assert _passes(conn) == [("en", 0, "done", "default")]
        assert _page(conn)["ocr_text"] == "Invoice total due\nMuseum of art"
        assert _page(conn)["language"] == "en"

    def test_the_text_is_exactly_what_the_engine_read_even_when_unsure(
        self, storage, conn, source, engines
    ):
        OcrSettings.set_languages(storage, "en")
        engines["en"].lines = JUNK

        Quick.run(storage, source)

        assert _page(conn)["ocr_text"] == "qzxv wplk\nmnbvc lkjh\nrtyuu"
        assert _passes(conn) == [("en", 0, "done", "default")]


class TestAutoDetection:
    def test_a_confident_english_read_settles_it_and_never_loads_telugu(
        self, storage, conn, source, engines
    ):
        Quick.run(storage, source)

        assert engines["te"].calls == 0
        assert _passes(conn) == [("en", 0, "done", "auto"), ("te", 1, "skipped", "auto")]
        assert _page(conn)["ocr_text"] == "Invoice total due\nMuseum of art"

    def test_an_unsure_english_read_queues_telugu_and_drops_the_made_up_lines(
        self, storage, conn, source, engines
    ):
        engines["en"].lines = JUNK

        Quick.run(storage, source)

        assert _passes(conn) == [("en", 0, "done", "auto"), ("te", 1, "pending", "auto")]
        page = _page(conn)
        assert page["ocr_text"] == ""
        assert page["confidence"] == 0.0
        assert engines["te"].calls == 0  # queued, not read yet
        assert conn.execute("SELECT status FROM document_index").fetchone()[0] == "indexed"

    def test_the_queued_pass_adds_the_telugu_text(self, storage, conn, source, engines):
        engines["en"].lines = JUNK
        Quick.run(storage, source)

        done = LanguagePasses.run_batch(storage, [Sources.get(storage, source.id)])

        assert done == 1
        page = _page(conn)
        assert page["ocr_text"] == "తెలుగు పాఠం\nఅమ్మ ఇల్లు"
        assert page["language"] == "te"
        assert page["ocr_langs"] == "te"
        assert _passes(conn)[1] == ("te", 1, "done", "auto")
        confidence = conn.execute(
            "SELECT confidence FROM document_languages WHERE language='te'"
        ).fetchone()[0]
        assert confidence == pytest.approx(0.92)
        assert page["confidence"] == pytest.approx(0.92)

    def test_the_queued_pass_records_its_confidence_under_its_own_language(
        self, storage, conn, source, engines
    ):
        from vethuq_core.stats import Confidence

        engines["en"].lines = JUNK
        Quick.run(storage, source)

        LanguagePasses.run_batch(storage, [Sources.get(storage, source.id)])

        by_language = {m.language: m for m in Confidence.get_metrics(storage)}
        assert by_language["te"].avg_confidence == pytest.approx(0.92)
        assert by_language["te"].page_count == 1

    def test_a_page_in_both_languages_keeps_both(self, storage, conn, source, engines):
        engines["en"].lines = [("Invoice total", 0.95), *JUNK]

        Quick.run(storage, source)

        assert _passes(conn)[1][2] == "pending"
        assert _page(conn)["ocr_text"] == "Invoice total"
        LanguagePasses.run_batch(storage, [Sources.get(storage, source.id)])
        page = _page(conn)
        assert page["ocr_text"] == "Invoice total\nతెలుగు పాఠం\nఅమ్మ ఇల్లు"
        assert page["ocr_langs"] == "en,te"
        assert page["language"] == "te"  # most of the text is Telugu

    def test_made_up_lines_from_the_second_language_are_dropped_too(
        self, storage, conn, source, engines
    ):
        engines["en"].lines = JUNK
        engines["te"].lines = [*TELUGU, ("ౘౙ ౝ", 0.2)]
        Quick.run(storage, source)

        LanguagePasses.run_batch(storage, [Sources.get(storage, source.id)])

        assert "ౘ" not in _page(conn)["ocr_text"]

    def test_nothing_found_does_not_trigger_the_second_language(
        self, storage, conn, source, engines
    ):
        engines["en"].lines = []

        Quick.run(storage, source)

        assert _passes(conn) == [("en", 0, "done", "auto"), ("te", 1, "skipped", "auto")]
        assert engines["te"].calls == 0

    def test_run_phased_does_the_first_pass_then_the_queue(self, storage, conn, source, engines):
        engines["en"].lines = JUNK

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert _page(conn)["ocr_text"] == "తెలుగు పాఠం\nఅమ్మ ఇల్లు"
        assert _passes(conn)[1][2] == "done"
        assert engines["en"].calls == 1  # the first language is not read a second time

    def test_a_failing_pass_is_recorded_and_not_retried(self, storage, conn, source, engines):
        engines["en"].lines = JUNK
        Quick.run(storage, source)

        def broken(image):
            raise RuntimeError("model crashed")

        engines["te"].recognize = broken
        skip = set()
        sources = [Sources.get(storage, source.id)]

        assert LanguagePasses.run_batch(storage, sources, skip_units=skip) == 1
        assert LanguagePasses.run_batch(storage, sources, skip_units=skip) == 0

        row = conn.execute("SELECT * FROM document_languages WHERE language='te'").fetchone()
        assert row["status"] == "error"
        assert "model crashed" in row["error_message"]
        assert _page(conn)["ocr_text"] == ""


class TestExplicitChoice:
    def test_a_flag_for_telugu_reads_in_telugu_and_never_loads_english(
        self, storage, conn, source, engines
    ):
        Quick.run(storage, source, languages="te")

        assert engines["en"].calls == 0
        assert _passes(conn) == [("te", 0, "done", "manual")]
        assert _page(conn)["ocr_text"] == "తెలుగు పాఠం\nఅమ్మ ఇల్లు"
        assert _page(conn)["language"] == "te"

    def test_a_source_can_choose_its_language(self, storage, conn, source, engines):
        Sources.set_languages(storage, source.id, "te")

        Quick.run(storage, Sources.get(storage, source.id))

        assert engines["en"].calls == 0
        assert _passes(conn) == [("te", 0, "done", "manual")]

    def test_the_flag_beats_the_source(self, storage, conn, source, engines):
        Sources.set_languages(storage, source.id, "te")

        Quick.run(storage, Sources.get(storage, source.id), languages="en")

        assert engines["te"].calls == 0
        assert _passes(conn) == [("en", 0, "done", "manual")]

    def test_the_source_beats_the_setting(self, storage, conn, source, engines):
        OcrSettings.set_languages(storage, "en")
        Sources.set_languages(storage, source.id, "te")

        Quick.run(storage, Sources.get(storage, source.id))

        assert _passes(conn) == [("te", 0, "done", "manual")]

    def test_a_language_list_detects_between_them(self, storage, conn, source, engines):
        engines["en"].lines = JUNK

        Quick.run(storage, source, languages="en,te")

        assert _passes(conn) == [("en", 0, "done", "auto"), ("te", 1, "pending", "auto")]

    def test_a_language_that_is_not_enabled_fails_the_file_with_how_to_get_it(
        self, storage, conn, source, engines
    ):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )

        Quick.run(storage, source, languages="te")

        row = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert row["status"] == "error"
        assert "Telugu" in row["error_message"]
        assert "pip install vethuq[lang-te]" in row["error_message"]
        assert engines["te"].calls == 0 and engines["en"].calls == 0

    def test_an_unknown_language_fails_the_file(self, storage, conn, source):
        Quick.run(storage, source, languages="klingon")

        row = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert row["status"] == "error"
        assert "Unknown language 'klingon'" in row["error_message"]
