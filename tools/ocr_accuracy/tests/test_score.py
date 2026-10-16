import pytest

from tools.ocr_accuracy import score


def test_a_perfect_read_has_no_errors():
    assert score.cer("Hello world", "Hello world") == 0.0
    assert score.word_recall("Hello world", "Hello world") == 1.0


def test_whitespace_is_ignored_by_cer():
    assert score.cer("a b  c\nd", "abcd") == 0.0


def test_cer_counts_edits_against_the_reference_length():
    assert score.cer("abcd", "abxd") == pytest.approx(0.25)
    assert score.cer("abcd", "") == 1.0
    assert score.cer("", "") == 0.0
    assert score.cer("", "x") == 1.0


def test_composed_and_decomposed_characters_are_the_same():
    assert score.cer("café", "café") == 0.0


def test_the_pure_python_distance_matches_the_fast_one(monkeypatch):
    pairs = [("kitten", "sitting"), ("", "abc"), ("same", "same"), ("flaw", "lawn")]
    expected = [score.distance(a, b) for a, b in pairs]
    monkeypatch.setattr(score, "_Fast", None)
    assert [score.distance(a, b) for a, b in pairs] == expected == [3, 3, 0, 2]


def test_word_recall_counts_repeats_and_ignores_case_and_order():
    assert score.word_recall("the cat the dog", "DOG the cat") == pytest.approx(0.75)
    assert score.word_recall("the cat", "the cats") == pytest.approx(0.5)
    assert score.word_recall("", "anything") == 1.0
