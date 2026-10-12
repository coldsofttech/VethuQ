"""Finds the built React interface."""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "VETHUQ_WEB_DIST"


class WebDistNotFoundError(FileNotFoundError):
    """The interface has not been built or packaged."""


def resolve_web_dist(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The folder holding `index.html`: explicit path, environment, package, or a checkout."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    elif os.environ.get(ENV_VAR):
        candidates.append(Path(os.environ[ENV_VAR]))
    else:
        candidates.append(here.parent / "web")
        # packages/desktop/src/vethuq_desktop/webdist.py -> the repository root
        candidates.append(here.parents[4] / "web" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    searched = ", ".join(str(c) for c in candidates)
    raise WebDistNotFoundError(
        f"The interface is not built (looked in: {searched}). "
        "Run `npm ci && npm run build` in web/."
    )
