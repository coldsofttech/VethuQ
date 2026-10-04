import pytest
from vethuq_core.settings import InvalidSettingValueError, OcrSettings
from vethuq_core.storage import Storage


class TestOcrSettings:
    def test_ocr_engine_defaults_to_quick_and_validates(self, storage: Storage):
        assert OcrSettings.get_engine(storage) == "quick"

        OcrSettings.set_engine(storage, "deep")
        assert OcrSettings.get_engine(storage) == "deep"

        with pytest.raises(InvalidSettingValueError):
            OcrSettings.set_engine(storage, "thorough")

    def test_reset_engine_goes_back_to_quick(self, storage: Storage):
        OcrSettings.set_engine(storage, "deep")

        OcrSettings.reset_engine(storage)

        assert OcrSettings.get_engine(storage) == OcrSettings.DEFAULT_ENGINE

    def test_reset_retry_attempts_goes_back_to_default(self, storage: Storage):
        OcrSettings.set_retry_attempts(storage, 9)

        OcrSettings.reset_retry_attempts(storage)

        assert OcrSettings.get_retry_attempts(storage) == OcrSettings.DEFAULT_RETRY_ATTEMPTS
