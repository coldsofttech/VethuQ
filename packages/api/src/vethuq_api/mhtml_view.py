"""An MHTML web archive made into one page a sandboxed frame can show.

An archive holds a page's HTML and the files it uses (pictures, styles, fonts, saved frames) as the
parts of a MIME message, which a browser cannot open when it is served over HTTP. So the preview
rewrites it: every reference the archive can answer (`<img src>`, `srcset`, `<link rel=stylesheet>`,
CSS `url(...)` and `@import`, `style` attributes, `cid:` references and `<iframe src>`) becomes
the thing itself (a `data:` address, a `<style>` block, an `srcdoc`), and a reference it cannot
answer is left alone, for the page's content security policy to refuse. Nothing is fetched and no
script runs: the result goes into the same sandboxed frame as an HTML file.

The text is read the way the Parquet and other previews read their files, by the API itself, not
through the licensed add-on.
"""

from __future__ import annotations

import base64
import html
import os
import re
import threading
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from urllib.parse import urldefrag, urljoin

MAX_BYTES = 128 * 1024 * 1024
MAX_PARTS = 5000
# How much of the archive's pictures and styles are put into the page. A page with more is shown
# with the first ones that fit, and says so.
INLINE_BUDGET = 24 * 1024 * 1024
MAX_DEPTH = 3
KEEP_FILES = 2
PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml"})
FONT_TYPES = frozenset(
    {
        "application/font-woff",
        "application/font-woff2",
        "application/x-font-woff",
        "application/x-font-ttf",
        "application/x-font-opentype",
        "application/vnd.ms-fontobject",
        "application/octet-stream",
    }
)

_TAG = re.compile(r"<(?P<tag>img|source|video|audio|link|iframe)\b(?P<attrs>[^>]*)>", re.I)
_ATTR = re.compile(
    r"""(?P<lead>\s)(?P<name>src|srcset|href|poster)\s*=\s*"""
    r"""(?:"(?P<d>[^"]*)"|'(?P<s>[^']*)'|(?P<u>[^\s>"']+))""",
    re.I,
)
_STYLE_BLOCK = re.compile(
    r"(?P<open><style\b[^>]*>)(?P<css>.*?)(?P<close></style\s*>)", re.I | re.S
)
_STYLE_ATTR = re.compile(r"""(?P<lead>\sstyle\s*=\s*)(?:"(?P<d>[^"]*)"|'(?P<s>[^']*)')""", re.I)
_CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s'"]*))\s*\)""", re.I)
_CSS_IMPORT = re.compile(
    r"""@import\s+(?:url\(\s*)?(?:"([^"]+)"|'([^']+)'|([^)\s;'"]+))\s*\)?[^;]*;""", re.I
)
_REL = re.compile(r"""\brel\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)


@dataclass
class Archive:
    """The parts of an archive, found by the addresses a page uses for them."""

    main: EmailMessage
    frames: list[EmailMessage]
    by_location: dict[str, EmailMessage]
    by_cid: dict[str, EmailMessage]
    address: str
    subject: str
    cache: dict[str, dict[str, object]] = field(default_factory=dict)


def _header(message: EmailMessage, name: str) -> str:
    try:
        value = message[name]
    except Exception:  # noqa: BLE001 - a malformed header must not lose the whole page
        return ""
    return " ".join(str(value).split()) if value is not None else ""


def _decoded(part: EmailMessage) -> tuple[str, str]:
    payload = part.get_payload(decode=True)
    data = payload if isinstance(payload, bytes) else b""
    declared = part.get_content_charset()
    if declared:
        try:
            return data.decode(declared, errors="replace"), declared
        except LookupError:
            pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def read(path: str) -> Archive:
    """The archive in `path`. Raises `ValueError` (with a reason a person can read) if it cannot
    be shown."""
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise ValueError(
            f"This file is {size // (1024 * 1024)} MB, too large to preview "
            f"(the limit is {MAX_BYTES // (1024 * 1024)} MB). Open it instead."
        )
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except RecursionError as error:
        raise ValueError("This is not a readable web archive (too deeply nested).") from error
    if not isinstance(message, EmailMessage) or not any(message.keys()):
        raise ValueError("This is not a web archive (it has no MIME headers).")
    parts: list[EmailMessage] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        parts.append(part)  # type: ignore[arg-type]
        if len(parts) > MAX_PARTS:
            raise ValueError("This web archive has too many parts to show.")
    pages = [p for p in parts if p.get_content_type() in PAGE_TYPES]
    if not pages:
        raise ValueError("This is not a web archive (there is no HTML page in it).")
    start = message.get_param("start")
    main = next(
        (
            p
            for p in pages
            if start and _header(p, "Content-ID").strip("<>") == str(start).strip("<>")
        ),
        pages[0],
    )
    by_location: dict[str, EmailMessage] = {}
    by_cid: dict[str, EmailMessage] = {}
    for part in parts:
        location = _header(part, "Content-Location")
        if location:
            by_location.setdefault(urldefrag(location)[0], part)
        cid = _header(part, "Content-ID").strip("<> ")
        if cid:
            by_cid.setdefault(cid, part)
    address = _header(message, "Snapshot-Content-Location") or _header(main, "Content-Location")
    return Archive(
        main=main,
        frames=[p for p in pages if p is not main],
        by_location=by_location,
        by_cid=by_cid,
        address=address,
        subject=_header(message, "Subject"),
    )


class _Inliner:
    """Rewrites the references of one archive's pages, within a budget of bytes."""

    def __init__(self, archive: Archive) -> None:
        self.archive = archive
        self.used = 0
        self.left_out = False

    # ----- finding what a reference names ----------------------------------------------------

    def find(self, reference: str, base: str) -> EmailMessage | None:
        reference = html.unescape(reference).strip()
        if not reference or reference.startswith(("data:", "#", "javascript:", "about:")):
            return None
        archive = self.archive
        if reference[:4].lower() == "cid:":
            return archive.by_location.get(reference) or archive.by_cid.get(
                reference[4:].strip("<> ")
            )
        whole = urldefrag(urljoin(base, reference))[0] if base else urldefrag(reference)[0]
        return archive.by_location.get(whole) or archive.by_location.get(urldefrag(reference)[0])

    def data_address(self, part: EmailMessage, allowed: tuple[str, ...]) -> str | None:
        """A `data:` address for a picture or font part, if the budget allows."""
        kind = part.get_content_type()
        if not (kind.startswith(allowed) or kind in FONT_TYPES and "font" in allowed):
            return None
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            return None
        if self.used + len(payload) > INLINE_BUDGET:
            self.left_out = True
            return None
        self.used += len(payload)
        return f"data:{kind};base64,{base64.b64encode(payload).decode('ascii')}"

    def picture(self, reference: str, base: str) -> str | None:
        part = self.find(reference, base)
        return None if part is None else self.data_address(part, ("image/",))

    # ----- CSS ------------------------------------------------------------------------------------

    def css(self, text: str, base: str, depth: int) -> str:
        """`text` with its `@import`s put in and its `url(...)`s made `data:` addresses."""

        def imported(found: re.Match[str]) -> str:
            target = self.find(next(g for g in found.groups() if g), base)
            if target is None or depth >= 2 or target.get_content_type() != "text/css":
                return ""
            sheet, _ = _decoded(target)
            return self.css(sheet, _header(target, "Content-Location") or base, depth + 1)

        def address(found: re.Match[str]) -> str:
            reference = next((g for g in found.groups() if g), "")
            part = self.find(reference, base)
            made = self.data_address(part, ("image/", "font")) if part is not None else None
            return f'url("{made}")' if made else found.group(0)

        return _CSS_URL.sub(address, _CSS_IMPORT.sub(imported, text))

    # ----- HTML ----------------------------------------------------------------------------------

    def page(self, markup: str, base: str, depth: int = 0) -> str:
        """`markup` with every reference the archive can answer answered."""

        def style_block(found: re.Match[str]) -> str:
            return f"{found['open']}{self.css(found['css'], base, depth)}{found['close']}"

        def style_attribute(found: re.Match[str]) -> str:
            raw = next(g for g in (found["d"], found["s"]) if g is not None)
            made = html.escape(self.css(html.unescape(raw), base, depth), quote=True)
            return f'{found["lead"]}"{made}"'

        def tag(found: re.Match[str]) -> str:
            name, attrs = found["tag"].lower(), found["attrs"]
            if name == "link":
                return self.link(found.group(0), attrs, base, depth)
            if name == "iframe":
                return self.frame(found.group(0), attrs, base, depth)

            def attribute(a: re.Match[str]) -> str:
                value = next(g for g in (a["d"], a["s"], a["u"]) if g is not None)
                if a["name"].lower() == "srcset":
                    candidates = []
                    for candidate in value.split(","):
                        pieces = candidate.split()
                        if not pieces:
                            continue
                        made = self.picture(pieces[0], base)
                        candidates.append(" ".join([made or pieces[0], *pieces[1:]]))
                    return f'{a["lead"]}srcset="{html.escape(", ".join(candidates), quote=True)}"'
                if a["name"].lower() == "href":
                    return a.group(0)
                made = self.picture(value, base)
                return f'{a["lead"]}{a["name"]}="{made}"' if made else a.group(0)

            return f"<{found['tag']}{_ATTR.sub(attribute, attrs)}>"

        markup = _STYLE_BLOCK.sub(style_block, markup)
        markup = _STYLE_ATTR.sub(style_attribute, markup)
        return _TAG.sub(tag, markup)

    def link(self, whole: str, attrs: str, base: str, depth: int) -> str:
        """A `<link rel=stylesheet>` the archive holds becomes a `<style>` block."""
        rel = _REL.search(attrs)
        if not rel or "stylesheet" not in next(g for g in rel.groups() if g is not None).lower():
            return whole
        href = _ATTR.search(" " + attrs.strip())
        if not href or href["name"].lower() != "href":
            return whole
        part = self.find(next(g for g in (href["d"], href["s"], href["u"]) if g is not None), base)
        if part is None or part.get_content_type() != "text/css":
            return whole
        sheet, _ = _decoded(part)
        css = self.css(sheet, _header(part, "Content-Location") or base, 0)
        safe = css.replace("</", "<\\/")  # a sheet cannot end its own <style>
        return f"<style>{safe}</style>"

    def frame(self, whole: str, attrs: str, base: str, depth: int) -> str:
        """An `<iframe>` whose page the archive holds carries that page in `srcdoc`."""
        src = _ATTR.search(" " + attrs.strip())
        if depth >= MAX_DEPTH or not src or src["name"].lower() != "src":
            return whole
        part = self.find(next(g for g in (src["d"], src["s"], src["u"]) if g is not None), base)
        if part is None or part.get_content_type() not in PAGE_TYPES:
            return whole
        markup, _ = _decoded(part)
        inner = self.page(markup, _header(part, "Content-Location") or base, depth + 1)
        rest = _ATTR.sub(lambda a: "" if a["name"].lower() == "src" else a.group(0), attrs)
        return f'<iframe{rest} srcdoc="{html.escape(inner, quote=True)}">'


def view(archive: Archive) -> dict[str, object]:
    """What the preview needs: the page's HTML as written (`text`, with the saved frames after
    it), the same page made self-contained (`rendered`), and facts about the archive."""
    markup, encoding = _decoded(archive.main)
    base = _header(archive.main, "Content-Location") or archive.address
    inliner = _Inliner(archive)
    rendered = inliner.page(markup, base)
    source = [markup]
    for frame in archive.frames:
        text, _ = _decoded(frame)
        source.append(
            f"<!-- Frame: {_header(frame, 'Content-Location') or 'saved page'} -->\n{text}"
        )
    text = "\n\n".join(source)
    return {
        "text": text,
        "rendered": rendered,
        "encoding": encoding,
        "address": archive.address,
        "subject": archive.subject,
        "frame_count": len(archive.frames),
        "incomplete": inliner.left_out,
        "longest_line": max((len(line) for line in text.split("\n")), default=0),
    }


class Cache:
    """The last few archives read, so switching between matches does not read the file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, int, int], Archive] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> Archive:
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
