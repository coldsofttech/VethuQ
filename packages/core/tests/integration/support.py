"""What the real-OCR integration tests share: loading `expected.json` and matching text to it.

`expected.json` sits next to each folder of fixture files and says what every file must come out
as. Native-only files need no OCR; files with a scanned page are read with the real PaddleOCR
models and run only when `VETHUQ_REAL_OCR=1` (see `.github/workflows/integration.yml`).
"""

from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

import pytest

# What share of a phrase's words OCR must have read for the phrase to count as found. OCR is not
# byte-exact, so a scanned page is matched by its words.
OCR_WORD_SHARE = 0.8

REAL_OCR = os.environ.get("VETHUQ_REAL_OCR") == "1"
FIXTURES = Path(__file__).parent / "fixtures"


def load(language: str, file_type: str) -> dict:
    return json.loads((FIXTURES / language / file_type / "expected.json").read_text("utf-8"))


def needs_ocr(entry: dict) -> bool:
    """Whether reading the file takes the OCR engine."""
    return entry.get("needs_ocr", False) or any(
        page["source"] != "native" for page in entry["pages"].values()
    )


def case(entry: dict):
    """A parametrized case for `entry`, skipped when it needs OCR and the real models are off."""
    marks = []
    if needs_ocr(entry) and not REAL_OCR:
        marks.append(pytest.mark.skip(reason="reads with real PaddleOCR: set VETHUQ_REAL_OCR=1"))
    if entry.get("lang_en"):
        marks.append(pytest.mark.lang_en)  # a file with English in it also belongs to `lang=en`
    return pytest.param(entry, id=entry["file"].split("_")[0], marks=marks)


def words(text: str) -> list[str]:
    return unicodedata.normalize("NFC", text).casefold().split()
