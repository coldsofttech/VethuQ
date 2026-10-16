import numpy as np
import pytest

from tools.ocr_accuracy import pages


@pytest.fixture(autouse=True)
def _font():
    try:
        pages.find_font("en")
    except pages.FontNotFound:
        pytest.skip("no English font on this machine")


def test_every_page_type_makes_a_bgr_image_with_the_reference_text():
    for page_type in pages.PAGE_TYPES:
        page = pages.make(page_type)
        assert page.image.dtype == np.uint8 and page.image.ndim == 3 and page.image.shape[2] == 3
        assert page.reference.strip() and page.page_type == page_type


def test_pages_are_deterministic():
    for page_type in ("scan", "poor", "photo"):
        assert np.array_equal(pages.make(page_type).image, pages.make(page_type).image)


def test_the_seed_changes_the_noise():
    assert not np.array_equal(pages.make("scan", seed=1).image, pages.make("scan", seed=2).image)


def test_sizes():
    assert pages.make("clean").image.shape[:2] == (1754, 1240)
    assert pages.make("large").image.shape[:2] == (3508, 2480)


def test_text_is_dark_on_a_light_page_and_degraded_pages_differ():
    clean = pages.make("clean").image
    assert clean.min() == 0 and clean.max() == 255
    assert not np.array_equal(clean, pages.make("scan").image)
    assert not np.array_equal(clean, pages.make("rotated").image)


def test_rotated_is_the_clean_page_turned_half_a_circle():
    assert np.array_equal(pages.make("rotated").image, pages.make("clean").image[::-1, ::-1])


def test_the_reference_is_what_was_drawn_so_no_line_runs_off_the_page():
    from PIL import ImageFont

    font = ImageFont.truetype(pages.find_font("en"), 34)
    width = pages.A4_150[0] * (1 - 2 * pages.MARGIN)
    for line in pages.make("clean").reference.splitlines():
        assert font.getlength(line) <= width


def test_wrap_breaks_at_spaces_and_keeps_every_word():
    from PIL import ImageFont

    font = ImageFont.truetype(pages.find_font("en"), 34)
    text = "one two three four five six seven eight nine ten eleven twelve"
    pieces = pages.wrap(text, font, 300)
    assert len(pieces) > 1 and " ".join(pieces) == text


def test_an_unknown_page_type_or_language():
    with pytest.raises(KeyError):
        pages.make("nonsense")
    with pytest.raises(KeyError):
        pages.make("clean", "xx")


def test_a_missing_font_is_reported(monkeypatch):
    monkeypatch.setattr(pages, "FONTS", {"en": ["/no/such/font.ttf"]})
    monkeypatch.delenv("VETHUQ_ACCURACY_FONT_EN", raising=False)
    with pytest.raises(pages.FontNotFound):
        pages.make("clean")


def test_a_font_can_be_chosen_by_environment(monkeypatch):
    path = pages.find_font("en")
    monkeypatch.setattr(pages, "FONTS", {"en": []})
    monkeypatch.setenv("VETHUQ_ACCURACY_FONT_EN", path)
    assert pages.find_font("en") == path
