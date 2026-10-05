import numpy as np
import pytest
from vethuq_core.semantic import Embedders, OnnxEmbedder, SemanticModel, SemanticModelError


class TestPooling:
    def test_averages_the_real_tokens_and_scales_to_unit_length(self):
        hidden = np.array([[[3.0, 0.0], [1.0, 0.0], [99.0, 99.0]]], dtype=np.float32)
        mask = np.array([[1, 1, 0]])  # the third token is padding

        vectors = OnnxEmbedder.pool(hidden, mask)

        assert vectors.shape == (1, 2)
        assert vectors[0] == pytest.approx([1.0, 0.0])

    def test_every_row_has_unit_length(self):
        rng = np.random.default_rng(0)
        hidden = rng.normal(size=(4, 7, 5)).astype(np.float32)
        mask = np.ones((4, 7), dtype=np.int64)

        norms = np.linalg.norm(OnnxEmbedder.pool(hidden, mask), axis=1)

        assert norms == pytest.approx(np.ones(4))

    def test_an_all_zero_row_stays_zero(self):
        hidden = np.zeros((1, 3, 2), dtype=np.float32)
        assert OnnxEmbedder.pool(hidden, np.ones((1, 3), dtype=np.int64)).tolist() == [[0.0, 0.0]]

    def test_the_model_is_read_at_512_tokens_into_384_numbers(self):
        assert SemanticModel.MAX_TOKENS == 512
        assert SemanticModel.QUERY_PREFIX == "query: "
        assert SemanticModel.PASSAGE_PREFIX == "passage: "


class TestEmbedders:
    def test_get_builds_the_embedder_once(self):
        built = []

        def factory():
            built.append(1)
            return object()

        Embedders.use(factory)
        try:
            assert Embedders.get() is Embedders.get()
            assert built == [1]
        finally:
            Embedders.use(None)

    def test_a_missing_model_that_cannot_be_downloaded_is_a_model_error(self, monkeypatch):
        def refuse(on_progress=None):
            raise SemanticModelError("offline")

        monkeypatch.setattr(SemanticModel, "download", staticmethod(refuse))
        Embedders.use(None)
        with pytest.raises(SemanticModelError, match="offline"):
            Embedders.get()
