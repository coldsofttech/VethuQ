"""Human-readable formatting of sizes, durations and timestamps, shared by every front end."""

from __future__ import annotations

from datetime import datetime


class Formatting:
    """Stateless formatters; `None` renders as `-` where a value can be missing."""

    MISSING = "-"

    @staticmethod
    def size(num_bytes: int | None) -> str:
        """`512 B`, `1.5 KB`, `2.0 MB`, `3.2 GB`."""
        if num_bytes is None:
            return Formatting.MISSING
        value = float(num_bytes)
        for unit in ("B", "KB", "MB"):
            if value < 1024:
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    @staticmethod
    def seconds(seconds: float | None) -> str:
        """`2.5s`."""
        return Formatting.MISSING if seconds is None else f"{seconds:.1f}s"

    @staticmethod
    def duration(seconds: float) -> str:
        """`45s` or `3m 5s`."""
        minutes, secs = divmod(int(seconds), 60)
        return f"{minutes}m {secs}s" if minutes else f"{secs}s"

    @staticmethod
    def timestamp(value: str | None) -> str:
        """An ISO timestamp in local time: `2026-10-04 12:30:05`."""
        if not value:
            return Formatting.MISSING
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def short_timestamp(value: str) -> str:
        """An ISO timestamp as `4 Oct 2026 12:30`; text that isn't a timestamp is returned as is."""
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return f"{parsed.day} {parsed.strftime('%b %Y %H:%M')}"
