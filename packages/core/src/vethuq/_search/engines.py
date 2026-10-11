"""Which search engines and normalizers are installed, and the levels a search runs them at."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vethuq._errors import _SearchOptionError, _SearchUnavailableError
from vethuq_addon_api import Normalizer, Pipeline, SearchEngineSpec

ALL = "all"
AUTO = "auto"
# The virtual engine that runs `semantic` together with a keyword engine and ranks the pages both
# find by reciprocal rank fusion (see `vethuq._search.ranking`).
HYBRID = "hybrid"
SEMANTIC = "semantic"
DEFAULT_KEYWORD = "full-text"


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
                        if use.optional:
                            continue
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
        return ", ".join([ALL, HYBRID, *(v.id for v in self.views())])

    def uses(self, view: _EngineView) -> list:
        """The normalizers of `view` that are installed (an optional one may not be)."""
        installed = self.normalizers()
        return [use for use in view.spec.normalizers if use.id in installed]

    def choose(self, engine: str, combine: str | None = None) -> list[_EngineView]:
        """The engines a search with `engine` (an id, `all` or `hybrid`) runs. Raises
        `SearchUnavailableError` if there are none. `combine` is the keyword engine `hybrid` runs
        beside `semantic` (`full-text` unless told)."""
        views = self.views()
        if engine == HYBRID:
            return self._hybrid(views, combine or DEFAULT_KEYWORD)
        if combine is not None:
            raise _SearchOptionError(
                "combine only applies to the hybrid engine.",
                "For example: engine='hybrid', combine='full-text'.",
                "combine",
            )
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

    def _hybrid(self, views: list[_EngineView], keyword: str) -> list[_EngineView]:
        """The semantic engine and the keyword engine `hybrid` combines."""
        by_id = {v.id: v for v in views}
        if keyword == SEMANTIC:
            raise _SearchOptionError(
                "The hybrid engine combines semantic with a keyword engine.",
                f"Name a keyword engine, for example {DEFAULT_KEYWORD}.",
                "combine",
            )
        chosen = []
        for wanted, role in ((SEMANTIC, "semantic"), (keyword, "keyword")):
            view = by_id.get(wanted)
            if view is None:
                raise _SearchUnavailableError(
                    f"The hybrid engine needs the {wanted} engine ({role}), which isn't installed.",
                    f"Engines: {self.known()}.",
                )
            if not view.available:
                raise _SearchUnavailableError(
                    f"The hybrid engine can't be used: the {view.spec.label} engine "
                    f"can't be used ({view.reason}).",
                    "Use client.search.engines() to see what is available.",
                )
            chosen.append(view)
        return chosen

    # ----- engine options ---------------------------------------------------------------------

    def check_options(
        self, options: Mapping[str, Mapping[str, str]], chosen: list[_EngineView]
    ) -> None:
        """Refuse options for an engine that isn't part of the search, that the engine doesn't
        declare, or whose value isn't one of its choices."""
        known = {v.id: v for v in self.views()}
        running = {v.id for v in chosen}
        for engine_id, values in options.items():
            view = known.get(engine_id)
            if view is None:
                raise _SearchOptionError(
                    f"There is no search engine {engine_id!r}.",
                    f"Engines: {self.known()}.",
                    engine_id,
                )
            if engine_id not in running:
                raise _SearchOptionError(
                    f"The {engine_id} engine isn't part of this search, so it takes no options.",
                    option=engine_id,
                )
            declared = {option.name: option for option in view.spec.options}
            for name, value in values.items():
                option = declared.get(name)
                where = f"{engine_id}.{name}"
                if option is None:
                    hint = (
                        f"Options: {', '.join(sorted(declared))}."
                        if declared
                        else f"The {engine_id} engine has no options."
                    )
                    raise _SearchOptionError(
                        f"The {engine_id} engine has no option {name!r}.", hint, where
                    )
                if option.choices and value not in option.choices:
                    raise _SearchOptionError(
                        f"{where} must be one of {', '.join(option.choices)}, not {value!r}.",
                        option=where,
                    )

    @staticmethod
    def parse_options(
        options: Mapping[str, Mapping[str, object]] | str | None,
    ) -> dict[str, dict[str, str]]:
        """`{"fuzzy": {"threshold": 0.7}}`, or the text `fuzzy.threshold=0.7,fuzzy.noise=high`."""
        if options is None:
            return {}
        found: dict[str, dict[str, str]] = {}
        if isinstance(options, str):
            for part in filter(None, (p.strip() for p in re.split(r"[,\s]+", options))):
                path, equals, value = part.partition("=")
                engine, dot, name = path.partition(".")
                if not equals or not dot or not engine or not name or not value:
                    raise _SearchOptionError(
                        f"{part!r} isn't ENGINE.OPTION=VALUE.",
                        "For example fuzzy.threshold=0.7.",
                        path or part,
                    )
                if name in found.setdefault(engine, {}):
                    raise _SearchOptionError(f"{path} was given twice.", option=path)
                found[engine][name] = value
            return found
        for engine, values in options.items():
            if not isinstance(values, Mapping):
                raise _SearchOptionError(
                    f"The options of {engine!r} must be a mapping of option to value.",
                    option=str(engine),
                )
            found[str(engine)] = {str(name): str(value) for name, value in values.items()}
        return found

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
        used = {use.id: use for use in view.spec.normalizers if use.id in installed}
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
