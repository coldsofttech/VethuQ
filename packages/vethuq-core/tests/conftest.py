import pytest
from vethuq_core.db import Db


@pytest.fixture
def conn(tmp_path):
    # check_same_thread=False: batch OCR hands this connection to worker threads,
    # same as the real index worker does.
    connection = Db.connect(tmp_path / "vethuq.db", check_same_thread=False)
    yield connection
    connection.close()
