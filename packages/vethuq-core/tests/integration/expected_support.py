"""What the real-OCR integration tests share: loading `expected.json` and matching text to it.

`expected.json` sits next to each folder of fixture files and says what every file must come out
as. `scripts/dev/generate_integration_expected.py` regenerates it.
"""

import json
import os
import unicodedata
from pathlib import Path

import pytest

# What share of a phrase's words OCR must have read for the phrase to count as found. OCR is not
# byte-exact (a stray character here and there), so a scanned page is matched by its words.
OCR_WORD_SHARE = 0.8

REAL_OCR = os.environ.get("VETHUQ_REAL_OCR") == "1"


def load(folder: Path) -> dict:
    return json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def needs_ocr(entry: dict) -> bool:
    """Whether reading the file takes the OCR engine (any page that is not native text)."""
    return any(page["source"] != "native" for page in entry["pages"].values())


def case(entry: dict):
    """A parametrized case for `entry`, skipped when it needs OCR and the real models are off."""
    marks = []
    if needs_ocr(entry) and not REAL_OCR:
        marks.append(
            pytest.mark.skip(
                reason="reads with real PaddleOCR: set VETHUQ_REAL_OCR=1 and the models"
            )
        )
    return pytest.param(entry, id=entry["file"][:2], marks=marks)


def words(text: str) -> list[str]:
    return unicodedata.normalize("NFC", text).casefold().split()


def contains(page_text: str, phrase: str, source: str) -> bool:
    """Native text must hold the phrase as written (whitespace aside); OCR text, most of its
    words."""
    page = " ".join(unicodedata.normalize("NFC", page_text).split())
    wanted = " ".join(unicodedata.normalize("NFC", phrase).split())
    if source == "native":
        return wanted in page
    have = set(words(page_text))
    needed = words(phrase)
    return sum(word in have for word in needed) / len(needed) >= OCR_WORD_SHARE
