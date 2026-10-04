import pytest
from vethuq_core.settings import InvalidSettingValueError, OcrSettings, Settings
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

    def test_reset_stability_check_goes_back_to_default(self, storage: Storage):
        OcrSettings.set_stability_check_seconds(storage, 0)

        OcrSettings.reset_stability_check_seconds(storage)

        # Read the stored value: the shared conftest stubs get_stability_check_seconds to 0.
        stored = Settings.get(storage, OcrSettings.STABILITY_CHECK_SECONDS_KEY)
        assert stored is not None
        assert float(stored) == OcrSettings.DEFAULT_STABILITY_CHECK_SECONDS
