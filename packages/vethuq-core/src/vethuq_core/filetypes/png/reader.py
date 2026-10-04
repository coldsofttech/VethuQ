"""Reader for `.png` files (the `type-png` file type)."""

from __future__ import annotations

from vethuq_core.readers.reader import ImageReader


class PngReader(ImageReader):
    """A .png file - identical to `ImageReader` today, split out as a hook for
    PNG-specific handling later (e.g. transparency)."""
