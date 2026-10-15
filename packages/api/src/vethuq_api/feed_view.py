"""An RSS or Atom feed made into entries for the feed preview.

The preview shows a feed the way a reader would, but its match has to be found in the text the index
kept: a feed is indexed as its title and description then, for each entry, its title, author, date,
categories, link and text (HTML stripped), one per line. So this module reads a feed into exactly
those lines, each with its kind (so the preview can lay it out) and its offset in the indexed text
(so the match can be marked). It reads feeds the way the RSS add-on does and a test holds the two
together; it does not go through the licensed add-on.
"""

from __future__ import annotations

import codecs
import html
import os
import re
import threading
from html.parser import HTMLParser
from typing import Any
from xml.etree.ElementTree import Element

MAX_BYTES = 64 * 1024 * 1024
# How many entries one answer holds; the window is placed around the match.
MAX_ENTRIES = 500
KEEP_FILES = 2

Line = tuple[str, str]  # (kind, text)


class _NotAFeed(ValueError):
    """A well-formed document that is not a feed."""


_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_ENTRY_NAMES = {"rss": "item", "rdf": "item", "atom": "entry"}


class _Text(HTMLParser):
    BREAKS = frozenset(
        {"p", "br", "div", "li", "ul", "ol", "tr", "table", "blockquote", "pre", "hr"}
        | {f"h{n}" for n in range(1, 7)}
    )
    SKIPPED = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIPPED:
            self.skipping += 1
        elif tag in self.BREAKS:
            self.parts.append("\n")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f" {alt} ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _local(tag: object) -> str:
    return (tag if isinstance(tag, str) else "").rsplit("}", 1)[-1]


def _plain(markup: str) -> list[str]:
    parser = _Text()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001, S110 - broken HTML is read as far as it goes
        pass
    lines = (_collapse(x) for x in "".join(parser.parts).splitlines())
    return [line for line in lines if line]


def _decode(data: bytes) -> str:
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding)
    declared = re.match(rb"""\s*<\?xml[^>]*encoding\s*=\s*["']([\w.:-]+)["']""", data)
    if declared:
        try:
            return data.decode(declared.group(1).decode("ascii").lower())
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # noqa: PLC0415 - only for a file that needs it

        found = from_bytes(data).best()
        if found is not None:
            return str(found)
    except ImportError:  # pragma: no cover - the feed add-on needs it
        pass
    if b"\x00" in data:
        raise ValueError("it contains binary data")
    return data.decode("cp1252", errors="replace")


# ----- a feed that parses -------------------------------------------------------------------


def _children(element: Element, name: str) -> list[Element]:
    return [c for c in element if _local(c.tag) == name]


def _first_text(element: Element, *names: str) -> str:
    for child in (c for name in names for c in _children(element, name)):
        text = _collapse("".join(child.itertext()))
        if text:
            return text
    return ""


def _body(entry: Element, names: tuple[str, ...]) -> list[str]:
    for child in (c for name in names for c in _children(entry, name)):
        raw = "".join(child.itertext())
        if not raw.strip():
            continue
        if child.get("type") == "text":
            lines = (_collapse(x) for x in raw.splitlines())
            return [line for line in lines if line]
        lines = _plain(raw)
        if lines:
            return lines
    return []


def _atom_link(entry: Element) -> str:
    links = _children(entry, "link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href", "").strip()
    return next((x.get("href", "").strip() for x in links if x.get("href")), "")


def _entry(entry: Element, kind: str) -> list[Line]:
    lines: list[Line] = []
    title = _first_text(entry, "title")
    if title:
        lines.append(("title", title))
    if kind == "atom":
        authors = [
            _first_text(a, "name") or _collapse("".join(a.itertext()))
            for name in ("author", "contributor")
            for a in _children(entry, name)
        ]
        author = ", ".join(a for a in authors if a)
        published = _first_text(entry, "published", "updated")
        categories = [c.get("label") or c.get("term") or "" for c in _children(entry, "category")]
        link = _atom_link(entry)
        text = _body(entry, ("content", "summary"))
    else:
        author = _first_text(entry, "creator", "author")
        published = _first_text(entry, "pubDate", "date")
        categories = [
            _collapse("".join(c.itertext()))
            for name in ("category", "subject")
            for c in _children(entry, name)
        ]
        link = _first_text(entry, "link")
        text = _body(entry, ("encoded", "description"))
    if author:
        lines.append(("author", f"Author: {author}"))
    if published:
        lines.append(("published", f"Published: {published}"))
    kept = [c for c in categories if c]
    if kept:
        lines.append(("categories", f"Categories: {', '.join(kept)}"))
    if link:
        lines.append(("link", f"Link: {link}"))
    lines.extend(("text", t) for t in text)
    return lines


def _from_tree(root: Element) -> dict[str, Any]:
    name = _local(root.tag)
    if name == "feed":
        kind = "atom"
        head = root
        entries = _children(root, "entry")
        description = _body(root, ("subtitle", "tagline"))
        language = root.get("{http://www.w3.org/XML/1998/namespace}lang")
        updated = _first_text(root, "updated")
    elif name in ("rss", "RDF"):
        kind = "rss" if name == "rss" else "rdf"
        channels = [c for c in root.iter() if _local(c.tag) == "channel"]
        if not channels:
            raise _NotAFeed("no channel")
        head = channels[0]
        entries = [e for e in root.iter() if _local(e.tag) == "item"]
        description = _body(head, ("description",))
        language = _first_text(head, "language") or None
        updated = _first_text(head, "lastBuildDate", "pubDate", "date")
    else:
        raise _NotAFeed("not a feed")
    top: list[Line] = []
    title = _first_text(head, "title")
    if title:
        top.append(("title", title))
    top.extend(("description", d) for d in description)
    return {
        "format": kind,
        "title": title or None,
        "language": language or None,
        "updated": updated or None,
        "well_formed": True,
        "head": top,
        "entries": [_entry(e, kind) for e in entries],
    }


# ----- a feed that does not -----------------------------------------------------------------


def _field(block: str, *names: str) -> str:
    for name in names:
        found = re.search(
            rf"<(?:\w+:)?{name}\b[^>]*>(.*?)</(?:\w+:)?{name}\s*>", block, flags=re.DOTALL
        )
        if found:
            value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", found.group(1), flags=re.DOTALL)
            if value.strip():
                return value
    return ""


def _flat(raw: str) -> str:
    return _collapse(html.unescape(re.sub(r"<[^>]*>", " ", raw)))


def _loose_lines(block: str) -> list[Line]:
    lines: list[Line] = []
    title = _flat(_field(block, "title"))
    if title:
        lines.append(("title", title))
    author = _flat(_field(block, "creator", "author", "name"))
    if author:
        lines.append(("author", f"Author: {author}"))
    published = _flat(_field(block, "pubDate", "published", "updated", "date"))
    if published:
        lines.append(("published", f"Published: {published}"))
    categories = [
        _flat(value)
        for value in re.findall(
            r"<(?:\w+:)?category\b[^>]*>(.*?)</(?:\w+:)?category\s*>", block, flags=re.DOTALL
        )
    ]
    kept = [c for c in categories if c]
    if kept:
        lines.append(("categories", f"Categories: {', '.join(kept)}"))
    link = _flat(_field(block, "link"))
    if not link:
        href = re.search(r"<link\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"']", block)
        link = href.group(1).strip() if href else ""
    if link:
        lines.append(("link", f"Link: {link}"))
    raw = _field(block, "encoded", "content", "description", "summary")
    lines.extend(("text", t) for t in _plain(html.unescape(raw) if "&lt;" in raw else raw))
    return lines


def _from_text(text: str) -> dict[str, Any]:
    stripped = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    kind = (
        "atom"
        if re.search(r"<(?:\w+:)?feed\b", stripped)
        else "rdf"
        if re.search(r"<(?:\w+:)?RDF\b", stripped)
        else "rss"
    )
    entry = _ENTRY_NAMES[kind]
    blocks = [
        m.group(0) for m in re.finditer(rf"<{entry}\b.*?</{entry}\s*>", stripped, flags=re.DOTALL)
    ]
    head = re.split(rf"<{entry}\b", stripped, maxsplit=1)[0]
    return {
        "format": kind,
        "title": _flat(_field(head, "title")) or None,
        "language": None,
        "updated": None,
        "well_formed": False,
        "head": _loose_lines(head),
        "entries": [_loose_lines(b) for b in blocks],
    }


# ----- reading ------------------------------------------------------------------------------


def read(path: str) -> dict[str, Any]:
    """The feed at `path`: its head lines and each entry's lines, with the feed's facts. Raises
    `ValueError` (with a message for the person) for a file that is not a feed."""
    unreadable = ValueError(
        "This feed cannot be read: it is damaged, or it is not an RSS or Atom feed."
    )
    try:
        from defusedxml.ElementTree import fromstring  # noqa: PLC0415 - only for feeds
    except ImportError as error:  # pragma: no cover - the RSS add-on needs it
        raise ValueError("defusedxml is not installed, so a feed cannot be shown here.") from error
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise ValueError(
            f"This feed is {size // (1024 * 1024)} MB, too large to preview. Open it instead."
        )
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        text = _decode(data)
        if "\x00" in text:
            raise unreadable
        try:
            return _from_tree(fromstring(data))
        except _NotAFeed:
            raise unreadable from None
        except Exception:  # noqa: BLE001, S110 - not well-formed, or entities: read it loosely
            pass
        if not re.search(r"<(?:\w+:)?(?:rss|feed|RDF)\b", text):
            raise unreadable
        return _from_text(text)
    except ValueError as error:
        if error is unreadable:
            raise
        raise unreadable from error
    except Exception as error:  # noqa: BLE001 - a damaged file is a message, never a server error
        raise unreadable from error


def window(feed: dict[str, Any], at: int | None) -> dict[str, Any]:
    """The answer for the preview: the feed's facts, the head lines and a window of at most
    `MAX_ENTRIES` entries around the character offset `at` (a match) in the indexed text. Each line
    is `{kind, text, start}`, `start` being its offset in that text (lines joined by a newline)."""
    offset = 0

    def lay(lines: list[Line]) -> list[dict[str, Any]]:
        nonlocal offset
        out = []
        for kind, text in lines:
            out.append({"kind": kind, "text": text, "start": offset})
            offset += len(text) + 1
        return out

    head = lay(feed["head"])
    laid = [lay(lines) for lines in feed["entries"]]
    first = 0
    if at is not None:
        for index, lines in enumerate(laid):
            if lines and lines[-1]["start"] + len(lines[-1]["text"]) >= at:
                first = max(0, index - MAX_ENTRIES // 4)
                break
        else:
            first = max(0, len(laid) - MAX_ENTRIES)
    shown = laid[first : first + MAX_ENTRIES]
    return {
        "format": feed["format"],
        "title": feed["title"],
        "language": feed["language"],
        "updated": feed["updated"],
        "well_formed": feed["well_formed"],
        "head": head,
        "entries": [{"lines": lines} for lines in shown],
        "first": first,
        "total": len(laid),
    }


class Cache:
    """The last few feeds read, so switching between matches does not read the file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> dict[str, Any]:
        real = os.path.realpath(path)
        stat = os.stat(real)
        key = (real, stat.st_mtime_ns, stat.st_size)
        with self._lock:
            found = self._files.pop(key, None)
            if found is not None:
                self._files[key] = found
                return found
        parsed = read(real)
        with self._lock:
            self._files[key] = parsed
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return parsed
