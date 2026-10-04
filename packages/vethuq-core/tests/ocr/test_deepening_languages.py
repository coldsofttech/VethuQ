"""Rotated (deeper) reads use the languages a page was read in."""

from unittest.mock import patch

import cv2
import numpy as np
import pytest
from test_language_flow import ENGLISH, JUNK, TELUGU, FakeEngine
from vethuq_core.ocr import Deepening, Ocr
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources


class TestPageLanguages:
    def test_the_recorded_languages_win(self):
        assert Deepening.page_languages("en", "en,te") == ("en", "te")

    def test_an_older_page_has_just_its_language(self):
        assert Deepening.page_languages("en", "") == ("en",)
        assert Deepening.page_languages("te", None) == ("te",)

    def test_a_page_with_no_language_has_none(self):
        assert Deepening.page_languages(None, "") == ()

    @pytest.mark.parametrize(
        "languages, expected",
        [((), False), (("en",), False), (("te",), True), (("en", "te"), True)],
    )
    def test_only_a_page_that_is_not_plain_english_needs_language_handling(
        self, languages, expected
    ):
        assert Deepening.needs_language_handling(languages) is expected


class TestReadAtAngle:
    @staticmethod
    def _engines():
        return {"en": FakeEngine("en", ENGLISH), "te": FakeEngine("te", TELUGU)}

    @staticmethod
    def _get(engines, calls):
        def get(storage, language=None):
            calls.append(language)
            return engines[language or "en"]

        return get

    def test_an_english_page_is_read_by_the_default_engine_as_before(self, storage):
        engines, calls = self._engines(), []
        with patch("vethuq_core.ocr.engines.Engines.get", side_effect=self._get(engines, calls)):
            texts, scores = Deepening.read_at_angle(storage, [np.zeros((4, 4, 3), np.uint8)], 90)

        assert calls == [None]
        assert texts == ["Invoice total due", "Museum of art"]
        assert scores == [0.96, 0.94]

    def test_a_telugu_page_is_read_in_telugu_and_wrong_script_lines_are_dropped(self, storage):
        engines, calls = self._engines(), []
        engines["te"].lines = [*TELUGU, ("Invoice total", 0.9)]
        with patch("vethuq_core.ocr.engines.Engines.get", side_effect=self._get(engines, calls)):
            texts, _ = Deepening.read_at_angle(
                storage, [np.zeros((4, 4, 3), np.uint8)], 90, ("te",)
            )

        assert calls == ["te"]
        assert texts == ["తెలుగు పాఠం", "అమ్మ ఇల్లు"]

    def test_a_page_in_both_languages_is_read_in_each_keeping_each_ones_own_script(self, storage):
        engines, calls = self._engines(), []
        engines["en"].lines = [*ENGLISH, ("తెలుగు", 0.9)]
        with patch("vethuq_core.ocr.engines.Engines.get", side_effect=self._get(engines, calls)):
            texts, _ = Deepening.read_at_angle(
                storage, [np.zeros((4, 4, 3), np.uint8)], 180, ("en", "te")
            )

        assert calls == ["en", "te"]
        assert texts == ["Invoice total due", "Museum of art", "తెలుగు పాఠం", "అమ్మ ఇల్లు"]

    def test_rotated_lines_must_still_clear_the_rotated_confidence_bar(self, storage):
        engines, calls = self._engines(), []
        engines["te"].lines = [("తెలుగు", 0.45)]  # below the rotated-read confidence bar
        with patch("vethuq_core.ocr.engines.Engines.get", side_effect=self._get(engines, calls)):
            texts, _ = Deepening.read_at_angle(
                storage, [np.zeros((4, 4, 3), np.uint8)], 90, ("te",)
            )

        assert texts == []


class TestFindUnits:
    def test_units_carry_the_pages_languages(self, conn, storage, tmp_path):
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(storage, folder)
        for name, language, langs in (("a.png", "en", ""), ("b.png", "te", "en,te")):
            document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
            ).lastrowid
            row = conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, "
                "status) VALUES (?, ?, ?, 'image', 'indexed')",
                (source.id, document_id, str(folder / name)),
            ).lastrowid
            conn.execute(
                "INSERT INTO image_pages (document_id, ocr_text, confidence, language, ocr_langs) "
                "VALUES (?, 'x', 0.9, ?, ?)",
                (row, language, langs),
            )
        conn.commit()

        units = Deepening.find_units(storage, [source], max_phase=2)

        assert [(u.file_path.name, u.languages) for u in units] == [
            ("a.png", ("en",)),
            ("b.png", ("en", "te")),
        ]


class TestEndToEnd:
    def test_a_telugu_file_is_read_in_telugu_at_every_angle(self, storage, conn, tmp_path):
        engines = {"en": FakeEngine("en", JUNK), "te": FakeEngine("te", TELUGU)}
        folder = tmp_path / "docs"
        folder.mkdir()
        cv2.imwrite(str(folder / "scan.png"), np.full((20, 40, 3), 255, dtype=np.uint8))
        source = Sources.add(storage, folder)
        OcrSettings.set_engine(storage, "moderate")

        with patch(
            "vethuq_core.ocr.engines.Engines.get",
            side_effect=lambda s, language=None: engines[language or "en"],
        ):
            Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        page = conn.execute("SELECT * FROM image_pages").fetchone()
        assert page["ocr_text"] == "తెలుగు పాఠం\nఅమ్మ ఇల్లు"
        assert page["language"] == "te"
        assert page["ocr_phase"] == 2
        # English read it once (the first pass); Telugu read it for the queued pass and again at
        # 90, 180 and 270 degrees.
        assert engines["en"].calls == 1
        assert engines["te"].calls == 4

    def test_an_english_file_never_loads_telugu_at_any_angle(self, storage, conn, tmp_path):
        engines = {"en": FakeEngine("en", ENGLISH), "te": FakeEngine("te", TELUGU)}
        folder = tmp_path / "docs"
        folder.mkdir()
        cv2.imwrite(str(folder / "scan.png"), np.full((20, 40, 3), 255, dtype=np.uint8))
        source = Sources.add(storage, folder)
        OcrSettings.set_engine(storage, "moderate")

        with patch(
            "vethuq_core.ocr.engines.Engines.get",
            side_effect=lambda s, language=None: engines[language or "en"],
        ):
            Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert engines["te"].calls == 0
        assert engines["en"].calls == 4
