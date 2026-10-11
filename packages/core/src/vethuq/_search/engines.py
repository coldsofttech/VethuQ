"""Which search engines and normalizers are installed, and the levels a search runs them at."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vethuq._errors import _SearchOptionError, _SearchUnavailableError
from vethuq_addon_api import Normalizer, Pipeline, SearchEngineSpec

ALL = "all"
AUTO = "auto"


@dataclass(frozen=True)
class _EngineView:
    spec: SearchEngineSpec
    available: bool
    reason: str

    @property
    def id(self) -> str:
        return self.spec.id


class _Engines:
    """The installed search engines (from add-ons), seen against the installed normalizers."""

    def __init__(
        self,
        specs: Callable[[], list[SearchEngineSpec]],
        normalizers: Callable[[], list[Normalizer]],
        stored: Callable[[str], str],
    ) -> None:
        self._specs = specs
        self._normalizers = normalizers
        self._stored = stored  # the user's saved level of a normalizer ("auto" if none)

    def normalizers(self) -> dict[str, Normalizer]:
        return {n.id: n for n in self._normalizers()}

    def views(self) -> list[_EngineView]:
        installed = self.normalizers()
        views = []
        for spec in self._specs():
            reason = ""
            if spec.engine is None or not spec.available:
                reason = spec.reason or "it has no engine"
            else:
                for use in spec.normalizers:
                    normalizer = installed.get(use.id)
                    if normalizer is None:
                        reason = f"it needs the {use.id} normalizer"
                        break
                    if use.default not in normalizer.levels:
                        reason = f"the {use.id} normalizer has no level {use.default!r}"
                        break
            views.append(_EngineView(spec, not reason, reason))
        return sorted(views, key=lambda v: (v.spec.strictness, v.id))

    def get(self, engine: str) -> _EngineView | None:
        return next((v for v in self.views() if v.id == engine), None)

    def known(self) -> str:
        return ", ".join([ALL, *(v.id for v in self.views())])

    def choose(self, engine: str) -> list[_EngineView]:
        """The engines a search with `engine` (an id, or `all`) runs. Raises
        `SearchUnavailableError` if there are none."""
        views = self.views()
        if engine == ALL:
            usable = [v for v in views if v.available and v.spec.in_all]
            if not usable:
                raise _SearchUnavailableError(
                    "No search engine is available.",
                    "Install a search engine add-on, for example vethuq-addon-like.",
                )
            return usable
        view = next((v for v in views if v.id == engine), None)
        if view is None:
            raise _SearchUnavailableError(
                f"There is no search engine {engine!r}.", f"Engines: {self.known()}."
            )
        if not view.available:
            raise _SearchUnavailableError(
                f"The {view.spec.label} engine can't be used: {view.reason}.",
                "Use client.search.engines() to see what is available.",
            )
        return [view]

    # ----- levels -----------------------------------------------------------------------------

    def check_explicit(self, explicit: Mapping[str, str]) -> None:
        installed = self.normalizers()
        for name, level in explicit.items():
            normalizer = installed.get(name)
            if normalizer is None:
                known = ", ".join(sorted(installed)) or "none"
                raise _SearchOptionError(
                    f"There is no normalizer {name!r}.", f"Normalizers: {known}.", name
                )
            if level not in normalizer.levels:
                raise _SearchOptionError(
                    f"{name} must be one of {', '.join(normalizer.levels)}, not {level!r}.",
                    option=name,
                )

    def levels(
        self, view: _EngineView, explicit: Mapping[str, str], *, strict: bool
    ) -> dict[str, str]:
        """The level each normalizer the engine uses runs at: what was asked for, else what the
        engine fixes, else the user's saved level (where the engine takes it), else the engine's
        own default. With `strict` (one engine named) asking for what the engine can't do raises
        `SearchOptionError`; otherwise it is simply not applied."""
        installed = self.normalizers()
        used = {use.id: use for use in view.spec.normalizers}
        if strict:
            for name in explicit:
                if name not in used:
                    raise _SearchOptionError(
                        f"The {view.id} engine doesn't use the {name} normalizer.",
                        option=name,
                    )
        result: dict[str, str] = {}
        for name, use in used.items():
            levels = installed[name].levels
            asked = explicit.get(name)
            if use.fixed:
                if asked is not None and asked != use.default and strict:
                    raise _SearchOptionError(
                        f"The {view.id} engine always runs {name} at {use.default!r}.",
                        option=name,
                    )
                result[name] = use.default
            elif asked is not None:
                result[name] = asked
            else:
                saved = self._stored(name) if use.stored else AUTO
                result[name] = saved if saved != AUTO and saved in levels else use.default
        return result

    def pipeline(self, levels: Mapping[str, str]) -> Pipeline:
        installed = self.normalizers()
        steps = [(installed[name], level) for name, level in levels.items()]
        return Pipeline(sorted(steps, key=lambda step: (step[0].order, step[0].id)))

    @staticmethod
    def parse(normalize: Mapping[str, str] | str | None) -> dict[str, str]:
        """`{"unicode": "full"}`, or the text `unicode=full,case=ignore`."""
        if normalize is None:
            return {}
        if isinstance(normalize, str):
            found: dict[str, str] = {}
            for part in filter(None, (p.strip() for p in re.split(r"[,\s]+", normalize))):
                name, equals, level = part.partition("=")
                if not equals or not name or not level:
                    raise _SearchOptionError(
                        f"{part!r} isn't NAME=LEVEL.", "For example unicode=full.", name or part
                    )
                if name in found:
                    raise _SearchOptionError(f"{name} was given twice.", option=name)
                found[name] = level
            return found
        return {str(name): str(level) for name, level in normalize.items()}
