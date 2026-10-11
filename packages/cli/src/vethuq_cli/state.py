"""What every command shares: whether `--json` was given, and one client for the whole run."""

from __future__ import annotations

import atexit
from pathlib import Path

import vethuq


class State:
    json: bool = False
    db_path: Path | None = None
    _client: vethuq.VethuQ | None = None

    @classmethod
    def client(cls) -> vethuq.VethuQ:
        if cls._client is None:
            cls._client = vethuq.VethuQ(db_path=cls.db_path) if cls.db_path else vethuq.VethuQ()
            atexit.register(cls.close)
        return cls._client

    @classmethod
    def close(cls) -> None:
        if cls._client is not None:
            try:
                cls._client.close()
            finally:
                cls._client = None

    @classmethod
    def reset(cls) -> None:
        cls.close()
        cls.json = False
        cls.db_path = None
