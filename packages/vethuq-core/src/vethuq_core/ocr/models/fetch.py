"""The child process that downloads OCR models: `python -m vethuq_core.ocr.models.fetch <name>...`
(the worker executable runs it for `--fetch-models` in the desktop build).

It is the only place the downloading needs PaddleX, so everything that manages models stays free
of it. One JSON object per line goes to stdout: `{"model": ..., "status": "downloading" | "ready" |
"failed", "error": ...}`. The exit code is 0 only if every model arrived.
"""

from __future__ import annotations

import json
import os
import sys

# Same as the engine: skip PaddleX's slow startup probe of the model hosters.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


class ModelFetch:
    @staticmethod
    def _emit(**event: str) -> None:
        sys.stdout.write(json.dumps(event) + "\n")
        sys.stdout.flush()

    @staticmethod
    def main(names: list[str]) -> int:
        try:
            from paddlex.inference.utils.official_models import official_models
        except ImportError as exc:
            for name in names:
                ModelFetch._emit(
                    model=name, status="failed", error=f"PaddleOCR is not installed ({exc})"
                )
            return 1
        failed = 0
        for name in names:
            ModelFetch._emit(model=name, status="downloading")
            try:
                official_models[name]
            except Exception as exc:  # noqa: BLE001 - any hoster/network failure is reported, not raised
                failed += 1
                ModelFetch._emit(model=name, status="failed", error=str(exc))
            else:
                ModelFetch._emit(model=name, status="ready")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(ModelFetch.main(sys.argv[1:]))
