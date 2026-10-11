"""Shared pieces for the worker tests."""

from __future__ import annotations

import numpy

from vethuq_addon_api import LanguageSpec, OcrRequest

EN = LanguageSpec("en", "English", default=True)
TE = LanguageSpec("te", "Telugu", "తెలుగు")
UNAVAILABLE = LanguageSpec("xx", "Gone", available=False, reason="licence lapsed")


def picture(shade: int = 255, width: int = 40, height: int = 30) -> numpy.ndarray:
    """A BGR pixel array."""
    return numpy.full((height, width, 3), shade, dtype=numpy.uint8)


def request(key: str, language: LanguageSpec = EN, shade: int = 255, **extra) -> OcrRequest:
    return OcrRequest(key, picture(shade), language, **extra)
