"""The worker image comes in variants, and the GitHub tier picks the smallest that fits a job.

The worker reads rendered pages: what a job needs of an image is the OCR phases it asks for and the
languages of its pages (every language is in every variant). The variants follow VethuQ's bundles:

    slim         the quick OCR phase, English and the licensed languages
    deep-scan    slim, and the moderate and deep OCR phases
    office, web, developer, open-office, email, image
                 slim, and the add-ons of that bundle
    full         everything the image has carried until now

`choose` takes what a job needs and returns the smallest variant that has it, or `full`.
The image build reads this table (`python variants.py --list NAME`), so the table and
the image cannot drift apart.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["VARIANTS", "Variant", "choose", "get", "tag"]

PHASES = ("quick", "moderate", "deep")

# Every variant has these, so every language is available whatever the variant.
LANGUAGES = (
    "vethuq-addon-telugu",
    "vethuq-addon-hindi",
    "vethuq-addon-urdu",
    "vethuq-addon-french",
    "vethuq-addon-spanish",
)
# What `pip install vethuq` itself requires (the free add-ons), so a wheel for each is always in the
# build. Listed here only so the build and its tests know the whole set.
CORE_DEPENDENCIES = (
    "vethuq-addon-english",
    "vethuq-addon-pdf",
    "vethuq-addon-txt",
    "vethuq-addon-csv",
    "vethuq-addon-markdown",
    "vethuq-addon-paddle",
    "vethuq-addon-ocr-quick",
    "vethuq-addon-like",
    "vethuq-addon-exact",
    "vethuq-addon-full-text",
    "vethuq-addon-case",
    "vethuq-addon-unicode",
)
DEEP = ("vethuq-addon-ocr-moderate", "vethuq-addon-ocr-deep")
IMAGE = tuple(f"vethuq-addon-{n}" for n in "png jpg tiff bmp gif webp jp2 svg heic".split())
WEB = tuple(f"vethuq-addon-{n}" for n in "html mhtml xml rss svg css json".split())
DEVELOPER = tuple(
    f"vethuq-addon-{n}"
    for n in (
        "yaml toml ini sql rst log js py java ts tsx jsx cs go rs php rb sh ps1 ipynb markdown "
        "html mhtml xml rss svg css json"
    ).split()
)
OPEN_OFFICE = tuple(f"vethuq-addon-{n}" for n in "odt ott ods ots odp otp".split())
EMAIL = ("vethuq-addon-eml", "vethuq-addon-msg")
OFFICE = tuple(
    f"vethuq-addon-{n}"
    for n in ("docx doc xlsx xls pptx ppt rtf eml dot dotx xlsm xlsb pptm pps ppsx msg").split()
)
DATA = tuple(f"vethuq-addon-{n}" for n in "csv tsv parquet json ndjson".split())
SEARCH = tuple(
    f"vethuq-addon-{n}"
    for n in (
        "like exact lexical full-text proximity fuzzy noise-fuzzy semantic case unicode leetspeak"
    ).split()
)
OTHER = ("vethuq-addon-autoscale",)


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    rank: int  # smaller is lighter; `choose` takes the lightest that fits
    extra: tuple[str, ...]  # add-ons beyond the base every variant has
    phases: tuple[str, ...] = ("quick",)

    @property
    def addons(self) -> tuple[str, ...]:
        """Every add-on distribution this variant installs beyond what `vethuq` requires."""
        return tuple(dict.fromkeys((*LANGUAGES, *self.extra)))


def _unique(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for group in groups for name in group))


VARIANTS: dict[str, Variant] = {
    v.name: v
    for v in (
        Variant("slim", "Quick OCR, every language", 1, ()),
        Variant("email", "slim and the email file types", 2, EMAIL),
        Variant("open-office", "slim and the OpenDocument file types", 3, OPEN_OFFICE),
        Variant("image", "slim and the image file types", 4, IMAGE),
        Variant("web", "slim and the web file types", 5, WEB),
        Variant("developer", "slim and the developer file types", 6, DEVELOPER),
        Variant("office", "slim and the office file types", 7, OFFICE),
        Variant("deep-scan", "slim and the moderate and deep OCR phases", 8, DEEP, PHASES),
        Variant(
            "full",
            "everything",
            9,
            _unique(DEEP, IMAGE, WEB, DEVELOPER, OPEN_OFFICE, OFFICE, DATA, SEARCH, OTHER),
            PHASES,
        ),
    )
}

DEFAULT = "full"


def get(name: str) -> Variant:
    try:
        return VARIANTS[name]
    except KeyError:
        raise ValueError(f"There is no worker image variant {name!r}.") from None


def tag(version: str, variant: str) -> str:
    """The image tag of a variant: `0.1.0-slim`. `full` is also the plain `0.1.0`."""
    return f"{version}-{get(variant).name}"


def everything() -> tuple[str, ...]:
    """Every add-on any variant installs, plus what `vethuq` requires: the wheels a build needs."""
    return _unique(CORE_DEPENDENCIES, *(v.addons for v in VARIANTS.values()))


def choose(phases: Iterable[str] = ("quick",), addons: Iterable[str] = ()) -> str:
    """The lightest variant with every OCR phase in `phases` and every add-on in `addons` (ids such
    as `docx` or distribution names); `full` when none fits. Unknown phases or add-ons never
    raise: they make `full` the answer, which has everything the image has."""
    wanted_phases = set(phases) or {"quick"}
    wanted = {a if a.startswith("vethuq-addon-") else f"vethuq-addon-{a}" for a in addons}
    base = set(CORE_DEPENDENCIES)
    for variant in sorted(VARIANTS.values(), key=lambda v: v.rank):
        if wanted_phases <= set(variant.phases) and wanted <= base | set(variant.addons):
            return variant.name
    return DEFAULT


def main(argv: list[str] | None = None) -> int:
    """`variants.py --list NAME | --extra NAME | --names | --all-addons`, for the build. It uses
    only the standard library, so the build runs the file itself."""
    parser = argparse.ArgumentParser(prog="variants.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", metavar="NAME", help="the add-ons of a variant, one per line")
    group.add_argument(
        "--extra", metavar="NAME", help="the add-ons of a variant beyond slim's, one per line"
    )
    group.add_argument("--names", action="store_true", help="the variant names, lightest first")
    group.add_argument("--all-addons", action="store_true", help="every add-on any variant needs")
    args = parser.parse_args(argv)
    if args.names:
        lines = [v.name for v in sorted(VARIANTS.values(), key=lambda v: v.rank)]
    elif args.all_addons:
        lines = list(everything())
    elif args.extra:
        try:
            lines = [a for a in get(args.extra).addons if a not in get("slim").addons]
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
    else:
        try:
            lines = list(get(args.list).addons)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
