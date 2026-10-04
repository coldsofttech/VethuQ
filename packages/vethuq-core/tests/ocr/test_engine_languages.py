import sys
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.ocr.engines import Engines, OcrResult
from vethuq_core.ocr.engines.paddle import PaddleOcrEngine


@pytest.fixture
def isolated_registry():
    saved = dict(Engines._factories)
    Engines._local.__dict__.pop("engines", None)
    yield
    Engines._factories.clear()
    Engines._factories.update(saved)
    Engines._local.__dict__.pop("engines", None)


def _fake_paddle(language=None):
    fake_paddleocr = MagicMock()
    page = {"rec_texts": ["తెలుగు"], "rec_scores": [0.9]}
    fake_paddleocr.PaddleOCR.return_value.predict.return_value = [page]
    with (
        patch.dict(sys.modules, {"paddleocr": fake_paddleocr}),
        patch("vethuq_core.ocr.engines.paddle._package_version", return_value="3.0.0"),
    ):
        engine = PaddleOcrEngine() if language is None else PaddleOcrEngine(language=language)
    # Reading happens outside the patched modules, as in the other engine tests.
    return engine, fake_paddleocr, engine.recognize("no-such-image.png")


class TestPaddleEngineLanguage:
    def test_english_is_the_default_and_loads_the_english_models(self):
        engine, fake, result = _fake_paddle()

        assert engine.language == "en"
        assert fake.PaddleOCR.call_args.kwargs["lang"] == "en"
        assert result.language == "en"

    def test_another_language_loads_its_own_models_and_labels_what_it_reads(self):
        engine, fake, result = _fake_paddle("te")

        assert engine.language == "te"
        assert fake.PaddleOCR.call_args.kwargs["lang"] == "te"
        assert isinstance(result, OcrResult) and result.language == "te"
        assert result.text == "తెలుగు"

    def test_the_other_settings_do_not_change_with_the_language(self):
        _, english, _ = _fake_paddle()
        _, telugu, _ = _fake_paddle("te")

        def rest(fake):
            return {k: v for k, v in fake.PaddleOCR.call_args.kwargs.items() if k != "lang"}

        assert rest(english) == rest(telugu)


class TestEngineRegistryLanguages:
    def test_the_default_language_is_built_without_naming_it(self, storage, isolated_registry):
        with patch("vethuq_core.ocr.engines.paddle.PaddleOcrEngine") as engine_cls:
            Engines.get(storage)
            Engines.get(storage, "en")

        engine_cls.assert_called_once_with(use_gpu=False)

    def test_another_language_gets_its_own_engine(self, storage, isolated_registry):
        with patch("vethuq_core.ocr.engines.paddle.PaddleOcrEngine") as engine_cls:
            engine_cls.side_effect = lambda **kwargs: MagicMock()
            english = Engines.get(storage)
            telugu = Engines.get(storage, "te")

        assert english is not telugu
        engine_cls.assert_any_call(use_gpu=False)
        engine_cls.assert_any_call(use_gpu=False, language="te")

    def test_each_language_is_built_once_per_thread(self, storage, isolated_registry):
        with patch("vethuq_core.ocr.engines.paddle.PaddleOcrEngine") as engine_cls:
            engine_cls.side_effect = lambda **kwargs: MagicMock()
            first = Engines.get(storage, "te")
            second = Engines.get(storage, "te")

        assert first is second
        assert engine_cls.call_count == 1

    def test_a_language_that_is_never_asked_for_is_never_loaded(self, storage, isolated_registry):
        with patch("vethuq_core.ocr.engines.paddle.PaddleOcrEngine") as engine_cls:
            Engines.get(storage)

        assert engine_cls.call_count == 1

    def test_an_unknown_language_is_refused(self, storage, isolated_registry):
        with pytest.raises(ValueError, match="Unknown OCR language 'xx'"):
            Engines.get(storage, "xx")

    def test_a_factory_that_takes_a_language_is_given_it(self, storage, isolated_registry):
        seen = []

        def factory(use_gpu, language):
            seen.append((use_gpu, language.id, language.paddle_lang))
            return MagicMock()

        Engines.register(Engines.DEFAULT, factory)

        Engines.get(storage, "te")

        assert seen == [(False, "te", "te")]

    def test_a_one_argument_factory_still_works_for_the_default_language(
        self, storage, isolated_registry
    ):
        built = []
        Engines.register(Engines.DEFAULT, lambda use_gpu: built.append(use_gpu) or MagicMock())

        Engines.get(storage)

        assert built == [False]

    def test_a_one_argument_factory_cannot_serve_another_language(self, storage, isolated_registry):
        Engines.register(Engines.DEFAULT, lambda use_gpu: MagicMock())

        with pytest.raises(ValueError, match="no support for the Telugu language"):
            Engines.get(storage, "te")
