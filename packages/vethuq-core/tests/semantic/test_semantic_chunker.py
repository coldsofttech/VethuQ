import pytest
from vethuq_core.semantic import Chunker


class TestChunker:
    def test_short_text_is_one_chunk(self):
        chunks = Chunker.split("The museum opens at nine.")
        assert [c.text for c in chunks] == ["The museum opens at nine."]
        assert (chunks[0].start, chunks[0].end) == (0, 25)

    def test_sentences_are_packed_up_to_the_limit(self):
        text = "First one here. Second one here. Third one here."
        chunks = Chunker.split(text, max_chars=33)
        assert [c.text for c in chunks] == ["First one here. Second one here.", "Third one here."]

    def test_every_chunk_is_its_own_span_of_the_text(self):
        text = "Alpha beta gamma.\nDelta epsilon zeta. Eta theta iota! Kappa lambda mu?"
        for chunk in Chunker.split(text, max_chars=30):
            assert text[chunk.start : chunk.end] == chunk.text
            assert len(chunk.text) <= 30

    def test_a_sentence_longer_than_the_limit_is_cut_at_a_space(self):
        text = "word " * 20
        chunks = Chunker.split(text, max_chars=22)
        assert len(chunks) > 1
        assert all(len(c.text) <= 22 and not c.text.endswith(" ") for c in chunks)
        assert " ".join(c.text for c in chunks).split() == text.split()

    def test_a_word_longer_than_the_limit_is_cut_anywhere(self):
        chunks = Chunker.split("x" * 50, max_chars=20)
        assert [len(c.text) for c in chunks] == [20, 20, 10]

    def test_the_telugu_danda_ends_a_sentence(self):
        text = "ఇది మొదటి వాక్యం। ఇది రెండవ వాక్యం।"
        chunks = Chunker.split(text, max_chars=20)
        assert [c.text for c in chunks] == ["ఇది మొదటి వాక్యం।", "ఇది రెండవ వాక్యం।"]

    @pytest.mark.parametrize("text", ["", "   \n  ", "12", "--- ... ---", "a."])
    def test_text_without_content_has_no_chunks(self, text):
        assert Chunker.split(text) == []

    def test_newlines_flattened_to_spaces_give_the_same_spans(self):
        text = "Line one is here\nLine two is here"
        assert [(c.start, c.end) for c in Chunker.split(text, 100)] == [
            (c.start, c.end) for c in Chunker.split(text.replace("\n", " "), 100)
        ]

    def test_default_limit_keeps_chunks_short(self):
        chunks = Chunker.split("A sentence that runs on and on and on. " * 100)
        assert len(chunks) > 5
        assert all(len(c.text) <= Chunker.MAX_CHARS for c in chunks)
