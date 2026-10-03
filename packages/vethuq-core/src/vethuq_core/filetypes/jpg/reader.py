"""Reader for `.jpg`/`.jpeg` files (the `type-jpg` file type)."""

from __future__ import annotations

from vethuq_core.readers.reader import ImageReader


class JpgReader(ImageReader):
    """A .jpg/.jpeg file - identical to `ImageReader` today, split out as a hook
    for JPEG-specific handling later."""
