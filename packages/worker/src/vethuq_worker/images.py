"""Page images to and from PNG. Needs Pillow (and numpy for pixel arrays)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from vethuq_worker.errors import JobError


class Images:
    """Converts page images to PNG for the job, and back to pixel arrays for OCR engines."""

    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    @classmethod
    def to_png(cls, image: Any) -> bytes:
        """PNG bytes for an image given as a file path or a BGR pixel array."""
        try:
            from PIL import Image
        except ImportError as error:  # pragma: no cover - environment dependent
            raise JobError("bad_payload", "Pillow is needed to send images.") from error
        if isinstance(image, str | Path):
            data = Path(image).read_bytes()
            if data.startswith(cls.PNG_SIGNATURE):
                return data
            picture = Image.open(io.BytesIO(data)).convert("RGB")
        else:
            array = image[..., ::-1] if getattr(image, "ndim", 0) == 3 else image  # BGR -> RGB
            picture = Image.fromarray(array)
        buffer = io.BytesIO()
        picture.save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def from_png(data: bytes) -> Any:
        """A BGR pixel array from PNG bytes (what OCR engines take)."""
        import numpy
        from PIL import Image

        try:
            picture = Image.open(io.BytesIO(data))
            picture.load()
        except Exception as error:  # noqa: BLE001 - any decode failure is the same to the caller
            raise JobError("bad_payload", "A page image can't be decoded.") from error
        return numpy.asarray(picture.convert("RGB"))[..., ::-1].copy()
