"""Look-alike ("leetspeak") substitutions and the noise-free text skeleton built from them.

Two search engines read the tables here: `leetspeak` (the spellings of a letter, including
multi-character ones such as `|\\|`) and `noise-fuzzy` (single characters only, folded into
classes). The substitutions are built in - nothing about them is stored or managed per user,
only which level applies (`SearchSettings.LEETSPEAK_LEVELS`).

The `skeleton` is what the database records next to a page's text so `noise-fuzzy` can find
candidate pages through a trigram index: the page's characters with the noise dropped and
every look-alike folded into one character per class, lower-cased. It is the coarsest
folding any level uses, so a page a level's search can match always has its skeleton match
too.
"""

from __future__ import annotations

import re
from functools import cache

from vethuq_core.search.normalizers.base import Folded
from vethuq_core.search.normalizers.unicode import UnicodeNormalizer

# Letter -> what it is written as, added at each level (cumulative).
BASIC = {
    "a": ("4", "@"),
    "e": ("3",),
    "i": ("1",),
    "l": ("1",),
    "o": ("0",),
    "s": ("5", "$"),
    "t": ("7",),
}
STANDARD = {
    "b": ("8",),
    "g": ("9", "6"),
    "i": ("!", "|"),
    "l": ("|",),
    "t": ("+",),
    "z": ("2",),
}
EXTENDED = {
    "a": ("/\\",),
    "b": ("|3",),
    "c": ("(", "[", "{"),
    "d": ("|)",),
    "f": ("ph",),
    "h": ("|-|",),
    "k": ("|<",),
    "l": ("|_",),
    "m": ("/\\/\\",),
    "n": ("|\\|",),
    "o": ("()",),
    "r": ("|2",),
    "u": ("|_|",),
    "v": ("\\/",),
    "w": ("\\/\\/",),
}
LEVEL_TABLES = {
    "off": (),
    "basic": (BASIC,),
    "standard": (BASIC, STANDARD),
    "extended": (BASIC, STANDARD, EXTENDED),
}
MAX_LEVEL = "extended"


class Leet:
    @staticmethod
    @cache
    def classes(level: str) -> dict[str, str]:
        """Every single character `level` treats as a look-alike, or as the letter it stands
        for, mapped to its class's representative letter.

        Characters that can stand for a common letter share a class (`i`, `l`, `1`, `!` and `|`
        are one), whose representative is its alphabetically first letter. A character that is
        not in any class is not in the result. Multi-character spellings are left out.
        """
        parent: dict[str, str] = {}

        def find(char: str) -> str:
            while parent.setdefault(char, char) != char:
                parent[char] = parent[parent[char]]
                char = parent[char]
            return char

        for table in LEVEL_TABLES[level]:
            for letter, written in table.items():
                for form in written:
                    if len(form) == 1:
                        parent[find(form)] = find(letter)
        groups: dict[str, list[str]] = {}
        for char in list(parent):
            groups.setdefault(find(char), []).append(char)
        classes = {}
        for members in groups.values():
            representative = min(char for char in members if char.isalpha())
            for char in members:
                classes[char] = representative
        return classes

    @staticmethod
    @cache
    def symbols() -> frozenset[str]:
        """The punctuation characters some level reads as a look-alike (`@ $ ! | + ( [ {`).

        They are kept in a skeleton and folded; every other symbol, and whitespace, is noise.
        """
        return frozenset(char for char in Leet.classes(MAX_LEVEL) if not char.isalnum())

    @staticmethod
    @cache
    def kept() -> re.Pattern[str]:
        """Matches each character a skeleton keeps: letters, digits and the look-alike symbols.

        The same characters `is_noise` says are not noise, found without calling it per
        character (`\\w` is a letter, a digit or an underscore, which is noise).
        """
        symbols = "".join(re.escape(char) for char in sorted(Leet.symbols()))
        return re.compile(rf"[^\W_]|[{symbols}]")

    @staticmethod
    @cache
    def folding(level: str, case_sensitive: bool) -> dict[int, str]:
        """A `str.translate` table doing what `fold` does to each kept character at `level`.

        Case-insensitively it expects the text lower-cased first (`str.lower`).
        """
        table: dict[int, str] = {}
        for char, representative in Leet.classes(level).items():
            table[ord(char)] = representative
            if case_sensitive and char.isalpha():
                table[ord(char.upper())] = representative.upper()
        return table

    @staticmethod
    def is_noise(char: str) -> bool:
        """Whether `char` is skipped when text is reduced to its skeleton."""
        return not char.isalnum() and char not in Leet.symbols()

    @staticmethod
    def fold(char: str, level: str, case_sensitive: bool) -> str:
        """`char` as its class's representative at `level`, lower-cased unless `case_sensitive`.

        Case-sensitive, a letter keeps its case (so a case difference is a difference), while
        a look-alike symbol or digit folds to the lower-case letter.
        """
        classes = Leet.classes(level)
        lowered = char.lower()
        if lowered in classes:
            representative = classes[lowered]
            return representative.upper() if case_sensitive and char != lowered else representative
        return char if case_sensitive else lowered

    @staticmethod
    def skeleton(text: str) -> str:
        """`text` folded as Unicode `full`, without its noise and with every look-alike folded,
        lower-cased.

        `"h @ e # l l o"` is `"haeiio"` (`l` and `i` share a class) and `"p@55w0rd"` is
        `"password"` - the text a page's search index is built on. It is level independent:
        the coarsest folding.
        """
        classes = Leet.classes(MAX_LEVEL)
        parts = []
        for char in UnicodeNormalizer().fold(text, "full").text:
            if Leet.is_noise(char):
                continue
            lowered = char.lower()
            parts.append(classes.get(lowered, lowered))
        return "".join(parts)


class LeetspeakNormalizer:
    """Folds look-alike characters into the letters they stand for (`h3ll0` is `hello`).

    Single characters only - `3` for `e`, `@` for `a`, and at higher levels `8`, `!`, `(` and
    so on - so positions never move. The multi-character spellings (`|\\|` for `n`) are not
    folded. Characters that can stand for several letters (`1` is `i` or `l`) share a class
    with all of them. It reads letters of either case, so it can follow the case normalizer.
    """

    name = "leetspeak"
    levels = ("off", "basic", "standard", "extended")
    identity = "off"

    def fold(self, text: str, level: str) -> Folded:
        if level == self.identity:
            return Folded(text)
        return Folded(text.translate(Leet.folding(level, True)))

    def char_table(self, level: str) -> dict[int, str] | None:
        return {} if level == self.identity else Leet.folding(level, True)

    def index_form(self, text: str) -> str:
        return self.fold(text, "extended").text
