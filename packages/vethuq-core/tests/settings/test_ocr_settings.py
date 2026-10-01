import sqlite3

import pytest
from vethuq_core.settings import InvalidSettingValueError, OcrSettings


class TestOcrSettings:
    def test_ocr_engine_defaults_to_quick_and_validates(self, conn: sqlite3.Connection):
        assert OcrSettings.get_engine(conn) == "quick"

        OcrSettings.set_engine(conn, "deep")
        assert OcrSettings.get_engine(conn) == "deep"

        with pytest.raises(InvalidSettingValueError):
            OcrSettings.set_engine(conn, "thorough")
