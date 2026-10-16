"""Whether an installed add-on was built for this Python and this platform.

A compiled add-on imported on the wrong interpreter fails only with `ModuleNotFoundError`, which
looks like a broken or missing add-on. The wheel records what it was built for in the `WHEEL` file
of its dist-info (`Tag: cp311-abi3-win_amd64`), so the loader reads that first and says so in words.
"""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Iterable
from importlib.metadata import Distribution

from packaging.tags import Tag, sys_tags

_PLATFORMS = (
    (re.compile(r"^win"), "Windows"),
    (re.compile(r"^(manylinux|musllinux|linux)"), "Linux"),
    (re.compile(r"^macosx"), "macOS"),
)
_PYTHON = re.compile(r"^(?:cp|py)(\d)(\d*)")


class _WheelTags:
    @staticmethod
    def of(dist: Distribution | None) -> frozenset[Tag]:
        """The tags in the distribution's `WHEEL` file; empty if it has none (an editable or
        source install), which is never a reason to refuse an add-on."""
        text = dist.read_text("WHEEL") if dist is not None else None
        found: set[Tag] = set()
        for line in (text or "").splitlines():
            key, _, value = line.partition(":")
            if key.strip() != "Tag":
                continue
            try:
                interpreter, abi, plat = value.strip().split("-")
            except ValueError:
                continue
            for p in interpreter.split("."):
                for a in abi.split("."):
                    for t in plat.split("."):
                        found.add(Tag(p, a, t))
        return frozenset(found)

    @staticmethod
    def platform_name(tag: str) -> str:
        if tag == "any":
            return "any platform"
        return next((name for pattern, name in _PLATFORMS if pattern.match(tag)), tag)

    @staticmethod
    def python_name(tags: Iterable[Tag]) -> str:
        """`3.12` for the newest Python the tags name (`cp312`, `cp311-abi3`: the minimum)."""
        versions = []
        for tag in tags:
            found = _PYTHON.match(tag.interpreter)
            if found and found.group(2):
                versions.append((int(found.group(1)), int(found.group(2))))
        if not versions:
            return "any Python 3"
        major, minor = max(versions)
        return f"Python {major}.{minor}"

    @staticmethod
    def problem(dist: Distribution | None, running: Iterable[Tag] | None = None) -> str | None:
        """Why the add-on can't run here, in words, or None when it can (or says nothing)."""
        wheel = _WheelTags.of(dist)
        if not wheel:
            return None
        supported = frozenset(running) if running is not None else frozenset(sys_tags())
        if wheel & supported:
            return None
        here_platforms = {t.platform for t in supported}
        wheel_platforms = {t.platform for t in wheel}
        here = f"Python {sys.version_info.major}.{sys.version_info.minor}"
        os_name = platform.system() or "this system"
        built = _WheelTags.python_name(wheel)
        if wheel_platforms.isdisjoint(here_platforms):
            kinds = sorted({_WheelTags.platform_name(p) for p in wheel_platforms})
            return (
                f"built for {' or '.join(kinds)}; VethuQ is running on {os_name} "
                f"({here}), which this add-on doesn't support"
            )
        return f"built for {built}; VethuQ is running {here}"
