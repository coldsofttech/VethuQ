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
