"""Settings that exist only because something is installed: the search normalizers, the options
of each search engine, and the settings add-ons declare for themselves."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from vethuq_api.setting_spec import BOOLEAN, CHOICE, INTEGER, NUMBER, TEXT, Spec

SEARCH_GROUP = "How text is matched"
_AUTO = "Automatic (each engine decides)"

# What the core does not say about the normalizers it ships: a name, what it does, its levels.
_NORMALIZERS: dict[str, tuple[str, str, dict[str, str]]] = {
    "case": (
        "Letter case",
        "Whether upper and lower case count as the same letter.",
        {"match": "Match case", "ignore": "Ignore case"},
    ),
    "unicode": (
        "Differently written characters",
        "How similar characters, such as accented letters and compatibility forms, are treated.",
        {"off": "Off: compare exactly", "basic": "Basic", "full": "Full"},
    ),
    "leetspeak": (
        "Look-alike symbols",
        "Whether symbols standing in for letters, like 4 for A, count as those letters.",
        {
            "off": "Off",
            "basic": "Basic",
            "standard": "Standard",
            "extended": "Extended",
        },
    ),
}


def _words(identifier: str) -> str:
    return identifier.replace("-", " ").replace("_", " ").capitalize()


def search_specs(client: Any) -> list[Spec]:
    """The normalizer levels and engine options of what is installed."""
    return [*_normalizer_specs(client), *_option_specs(client)]


def _normalizer_specs(client: Any) -> list[Spec]:
    specs = []
    for normalizer in client.search.normalizers():
        label, description, names = _NORMALIZERS.get(
            normalizer.id,
            (_words(normalizer.id), f"How the {normalizer.id} normalizer treats text.", {}),
        )
        options = [{"value": "auto", "label": _AUTO}] + [
            {"value": level, "label": names.get(level, _words(level))}
            for level in normalizer.levels
        ]
        specs.append(
            Spec(
                id=f"search.normalize.{normalizer.id}",
                section="search",
                group=SEARCH_GROUP,
                group_note="What counts as the same character in a search. Automatic lets each "
                "search engine use its own level.",
                label=label,
                description=description,
                kind=CHOICE,
                default="auto",
                read=lambda c, n=normalizer.id: c.settings.search.get_normalizer(n),
                write=lambda c, v, n=normalizer.id: c.settings.search.set_normalizer(n, v),
                reset=lambda c, n=normalizer.id: c.settings.search.reset_normalizer(n),
                options=lambda _c, o=options: o,
                note="Applies to the next search.",
            )
        )
    return specs


def _declared_options(client: Any) -> dict[str, tuple[Any, ...]]:
    """`{engine id: its options}`, each with a name, default and, often, the allowed choices."""
    try:
        # The core's own list of declared options. It has no public accessor yet; the CLI reads the
        # same information to build `settings search <engine> <option>`.
        declared = client.settings.search._options()  # noqa: SLF001
        if declared:
            return {engine: tuple(options) for engine, options in declared.items()}
    except (AttributeError, TypeError):
        pass
    # Without it, the public listing still gives each option's name and default.
    return {
        engine.id: tuple(
            SimpleNamespace(name=name, description="", default=default, choices=())
            for name, default in engine.options.items()
        )
        for engine in client.search.engines()
        if engine.options
    }


def _option_specs(client: Any) -> list[Spec]:
    labels = {engine.id: engine.label for engine in client.search.engines()}
    descriptions = {engine.id: engine.description for engine in client.search.engines()}
    specs = []
    for engine, options in _declared_options(client).items():
        title = f"{labels.get(engine, _words(engine))} engine"
        for option in options:
            kind = _kind_of(option.default, bool(option.choices))
            specs.append(
                Spec(
                    id=f"search.option.{engine}.{option.name}",
                    section="search",
                    group=title,
                    group_note=descriptions.get(engine, ""),
                    label=_words(option.name),
                    description=option.description
                    or f"The {option.name} the {labels.get(engine, engine)} engine uses unless a "
                    "search says otherwise.",
                    kind=kind,
                    default=_convert(kind, option.default),
                    read=lambda c, e=engine, o=option, k=kind: _convert(
                        k, c.settings.search.get_option(e, o.name)
                    ),
                    write=lambda c, v, e=engine, o=option: c.settings.search.set_option(
                        e, o.name, str(v)
                    ),
                    reset=lambda c, e=engine, o=option: c.settings.search.reset_option(e, o.name),
                    options=(
                        lambda _c, o=option: [{"value": x, "label": _words(x)} for x in o.choices]
                    )
                    if option.choices
                    else None,
                    minimum=0 if kind in (INTEGER, NUMBER) else None,
                    note="Applies to the next search.",
                )
            )
    return specs


def _kind_of(default: str, has_choices: bool) -> str:
    if has_choices:
        return CHOICE
    if re.fullmatch(r"-?\d+", default or ""):
        return INTEGER
    if re.fullmatch(r"-?\d+\.\d+", default or ""):
        return NUMBER
    return TEXT


def _convert(kind: str, value: Any) -> Any:
    """A setting the core keeps as text, as the kind of value it is (text if it does not parse)."""
    try:
        if kind == INTEGER:
            return int(value)
        if kind == NUMBER:
            return float(value)
    except (TypeError, ValueError):
        return value
    return value


_UNITS = (
    ("-minutes", "minutes"),
    ("-days", "days"),
    ("-hours", "hours"),
    ("-seconds", "seconds"),
    ("-mb", "MB"),
    ("-percent", "%"),
)


def addon_specs(client: Any) -> list[Spec]:
    """The settings of every installed add-on that declares some (`vethuq settings addons ...`).

    An add-on setting is text to the core (`get` returns text, `set` takes text), so what kind of
    control it gets is guessed from its value: a list of choices, true/false, a whole number, a
    number, or free text.
    """
    specs = []
    for _addon_id, group in client.addons.cli():
        for setting in group.settings or ():
            specs.append(_addon_spec(client, group, setting))
    specs.extend(_stopped_specs(client))
    return specs


def _stopped_specs(client: Any) -> list[Spec]:
    """One read-only row for every installed add-on that is not running. Its settings can't be
    listed (it did not load), so the row says why, instead of leaving the add-on out."""
    try:
        infos = list(client.addons.list())
    except Exception:  # noqa: BLE001 - a client without a list shows only what runs
        return []
    return [
        Spec(
            id=f"{info.id}.status",
            section="addons",
            group=info.name,
            label="Status",
            description="Whether this add-on is running.",
            kind=TEXT,
            default=None,
            read=lambda _c, i=info: f"Not running ({i.status.value})",
            write=None,
            reset=None,
            resettable=False,
            catches=(Exception,),
            note=info.detail or "It is not running.",
        )
        for info in infos
        if info.status.value != "loaded"
    ]


def _addon_spec(client: Any, group: Any, setting: Any) -> Spec:
    heading = (group.help or group.name).rstrip(".")
    base = {
        "id": f"{group.name}.{setting.name}",
        "section": "addons",
        "group": heading,
        "label": _words(setting.name),
        "description": setting.help,
        "unit": next((unit for suffix, unit in _UNITS if setting.name.endswith(suffix)), ""),
        "resettable": setting.reset is not None,
        "reset": (lambda c, s=setting: s.reset(c)) if setting.reset is not None else None,
        "catches": (Exception,),
        "default": None,
    }
    try:
        current = str(setting.get(client))
    except Exception as error:  # noqa: BLE001  # for example the add-on is not licensed
        return Spec(
            **base,
            kind=TEXT,
            read=lambda _c: None,
            write=None,
            note=f"Unavailable: {error}",
        )

    if setting.choices:
        return Spec(
            **base,
            kind=CHOICE,
            read=lambda c, s=setting: str(s.get(c)),
            write=lambda c, v, s=setting: s.set(c, v),
            options=lambda _c, s=setting: [{"value": x, "label": _words(x)} for x in s.choices],
        )
    if current.lower() in ("true", "false"):
        return Spec(
            **base,
            kind=BOOLEAN,
            read=lambda c, s=setting: str(s.get(c)).lower() == "true",
            write=lambda c, v, s=setting: s.set(c, "true" if v else "false"),
        )
    kind = _kind_of(current, False)
    span = re.search(r"\((\d+) to (\d+)\)", setting.help or "")
    return Spec(
        **base,
        kind=kind,
        read=lambda c, s=setting, k=kind: _convert(k, s.get(c)),
        write=lambda c, v, s=setting: s.set(c, str(v)),
        minimum=int(span.group(1)) if span else None,
        maximum=int(span.group(2)) if span else None,
    )
