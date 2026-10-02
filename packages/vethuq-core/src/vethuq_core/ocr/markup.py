"""Text extraction for HTML and XML files - read straight from the markup, no OCR."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element


@dataclass(frozen=True)
class Decoded:
    text: str
    encoding: str
    confidence: float


class Markup:
    """Decodes and flattens HTML/XML files into searchable plain text."""

    # Byte-order marks other than UTF-8 make the data look like it contains NUL bytes.
    _WIDE_BOMS = (
        codecs.BOM_UTF32_LE,
        codecs.BOM_UTF32_BE,
        codecs.BOM_UTF16_LE,
        codecs.BOM_UTF16_BE,
    )

    # Confidence when the encoding had to be guessed rather than being declared (a BOM,
    # an XML declaration, a `<meta charset>`) or being valid UTF-8, which is near-proof.
    GUESSED_CONFIDENCE = 0.8
    # Confidence when decoding had to replace undecodable bytes.
    LOSSY_CONFIDENCE = 0.5
    # Confidence when an XML file wasn't well-formed and was read as loose text instead.
    UNPARSED_CONFIDENCE = 0.5

    # Elements whose content never reads as page text.
    _HTML_SKIP = ("script", "style", "template", "noscript", "head")

    # Elements that end a line of text; everything else flows inline.
    _HTML_BLOCKS = (
        "address article aside blockquote body dd details dialog div dl dt fieldset "
        "figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr li main menu nav "
        "ol p pre section summary svg table tbody tfoot thead title tr ul caption"
    ).split()

    # `url(...)`, quoted or not, in CSS that's already had its comments stripped.
    _CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s'"]*))\s*\)""", re.IGNORECASE)
    _CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
    _CSS_DATA_URL = re.compile(r"""url\(\s*(["']?)\s*data:.*?\1\s*\)""", re.IGNORECASE | re.DOTALL)
    _CSS_CHARSET = re.compile(rb"""^(?:\xef\xbb\xbf)?@charset\s+["']([\w.:-]+)["']""")

    _META_TEXT_NAMES = ("description", "keywords", "title", "og:title", "og:description")

    @staticmethod
    def decode(data: bytes, *, is_html: bool, known_encodings: tuple[str, ...] = ()) -> Decoded:
        """Decode `data` to text, working the encoding out from its BOM, its declaration
        (`<meta charset>` / `<?xml encoding?>`), or by detection.

        `known_encodings` are tried first and, if one decodes the data, trusted outright
        (e.g. a CSS `@charset`). Raises `ValueError` for data that's evidently binary.
        """
        from bs4 import UnicodeDammit

        dammit = UnicodeDammit(
            data, is_html=is_html, known_definite_encodings=list(known_encodings)
        )
        if dammit.unicode_markup is None or dammit.original_encoding is None:
            raise ValueError("file could not be decoded as text")
        # Wide encodings (UTF-16/32) are recognised and decoded above, so a NUL that's
        # still in the text means binary data rather than markup.
        if "\x00" in dammit.unicode_markup:
            raise ValueError("file is not HTML/XML text (contains binary data)")

        encoding = dammit.original_encoding
        if dammit.contains_replacement_characters:
            confidence = Markup.LOSSY_CONFIDENCE
        elif (
            dammit.declared_html_encoding
            or encoding.lower() in ("utf-8", "ascii")
            or encoding in known_encodings
        ):
            confidence = 1.0
        elif data.startswith(codecs.BOM_UTF8) or data.startswith(Markup._WIDE_BOMS):
            confidence = 1.0
        else:
            confidence = Markup.GUESSED_CONFIDENCE
        return Decoded(dammit.unicode_markup, encoding, confidence)

    # --- HTML ----------------------------------------------------------------------

    @staticmethod
    def html_text(markup: str) -> tuple[str, list[str]]:
        """`(text, image_sources)` for an HTML document.

        The text is what a reader sees: no tags, scripts, styles or comments, block
        elements on their own lines, plus `<title>`, descriptive `<meta>` tags and images'
        `alt` text; text inside an inline `<svg>` is included. `image_sources` are the raw
        references to images in document order - `<img src>`, `srcset` candidates (also on
        `<picture>`'s `<source>`), then CSS `url(...)` from `<style>` blocks and `style`
        attributes (duplicates kept - callers resolve and de-duplicate them).
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(markup, "html.parser")

        extra: list[str] = []
        if soup.title and soup.title.string:
            extra.append(soup.title.string)
        for meta in soup.find_all("meta"):
            name = meta.get("name") or meta.get("property")
            content = meta.get("content")
            if (
                isinstance(name, str)
                and name.lower() in Markup._META_TEXT_NAMES
                and isinstance(content, str)
            ):
                extra.append(content)

        css = [style.get_text() for style in soup.find_all("style")]
        css += [v for tag in soup.find_all(style=True) if isinstance(v := tag.get("style"), str)]

        sources: list[str] = []
        for tag in soup.find_all(["img", "source"]):
            src = tag.get("src") if tag.name == "img" else None
            if isinstance(src, str) and src.strip():
                sources.append(src.strip())
            srcset = tag.get("srcset")
            if isinstance(srcset, str):
                sources += [c.split()[0] for c in srcset.split(",") if c.strip()]
        for chunk in css:
            sources += Markup.css_urls(chunk)

        for tag in soup.find_all(Markup._HTML_SKIP):
            tag.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        for tag in soup.find_all("img"):
            alt = tag.get("alt")
            if isinstance(alt, str) and alt.strip():
                tag.replace_with(f" {alt} ")
        for tag in soup.find_all(Markup._HTML_BLOCKS):
            tag.insert_before("\n")
            tag.insert_after("\n")
        for tag in soup.find_all(["td", "th", "text"]):
            tag.insert_after(" ")

        body = Markup._normalize(soup.get_text())
        lines = (*(Markup._collapse(e) for e in extra), body)
        return "\n".join(line for line in lines if line), sources

    # --- CSS -----------------------------------------------------------------------

    @staticmethod
    def decode_css(data: bytes) -> Decoded:
        """Decode a stylesheet, honouring a leading `@charset` rule (else a BOM, else
        detection - see `decode`)."""
        match = Markup._CSS_CHARSET.match(data)
        known: tuple[str, ...] = ()
        if match:
            known = (match.group(1).decode("ascii"),)
        return Markup.decode(data, is_html=False, known_encodings=known)

    @staticmethod
    def css_urls(css: str) -> list[str]:
        """The raw `url(...)` references in `css` (comments ignored), in order. `data:`
        URIs are included - callers decide what's followable."""
        uncommented = Markup._CSS_COMMENT.sub("", css)
        return [
            (quoted or single or bare).strip()
            for quoted, single, bare in Markup._CSS_URL.findall(uncommented)
            if (quoted or single or bare).strip()
        ]

    @staticmethod
    def css_text(css: str) -> tuple[str, list[str]]:
        """`(text, url_references)` for a stylesheet.

        The text is the stylesheet itself - selectors, values, `content:` strings and
        comments (often its only documentation) - with whitespace collapsed, one rule
        per line even when minified, and inline `data:` URIs (base64 blobs) dropped.
        """
        text = Markup._CSS_DATA_URL.sub("url(data:)", css)
        text = text.replace("}", "}\n")
        return Markup._normalize(text), Markup.css_urls(css)

    # --- SVG -----------------------------------------------------------------------

    @staticmethod
    def svg_text(data: bytes) -> str:
        """The text an SVG image displays (`<text>`) or describes (`<title>`, `<desc>`),
        one element per line. Empty for anything that isn't well-formed SVG."""
        from xml.etree.ElementTree import ParseError

        from defusedxml.ElementTree import fromstring

        try:
            root = fromstring(data)
        except (ParseError, ValueError):
            return ""
        lines = []
        for element in root.iter():
            if Markup._local_name(element.tag) in ("text", "title", "desc"):
                line = Markup._collapse("".join(element.itertext()))
                if line:
                    lines.append(line)
        return "\n".join(lines)

    # --- XML -----------------------------------------------------------------------

    @staticmethod
    def xml_text(data: bytes) -> str:
        """Text of a well-formed XML document, one line per value, each under the element
        path it sits at (`catalog/book/title: Dune`; an attribute is `catalog/book@id: 7`),
        so a search can match the name as well as the value.

        Raises `ParseError` when the document isn't well-formed, and `ValueError` (from
        `defusedxml`) when it uses constructs that are unsafe to expand (entity
        declarations - billion-laughs and external entity attacks); `XmlReader` falls
        back to `loose_text` for either.
        """
        from defusedxml.ElementTree import fromstring

        root = fromstring(data)
        lines: list[str] = []
        Markup._walk_xml(root, lines)
        return "\n".join(lines)

    @staticmethod
    def _local_name(tag: object) -> str:
        name = tag if isinstance(tag, str) else ""
        return name.rsplit("}", 1)[-1]

    @staticmethod
    def _walk_xml(root: Element, lines: list[str]) -> None:
        # Iterative: deeply-nested documents would otherwise hit the recursion limit.
        # Entries are `(element, path-of-parent)`; text trailing a child element (mixed
        # content) is queued as a `(None, "path: text")` line so order is preserved.
        stack: list[tuple[Element | None, str]] = [(root, "")]
        while stack:
            current, base = stack.pop()
            if current is None:
                lines.append(base)
                continue
            name = Markup._local_name(current.tag)
            path = f"{base}/{name}" if base else name

            for key, value in current.attrib.items():
                value = Markup._collapse(value)
                if value:
                    lines.append(f"{path}@{Markup._local_name(key)}: {value}")
            text = Markup._collapse(current.text or "")
            if text:
                lines.append(f"{path}: {text}")

            # Children (and the text trailing each) come out in document order; the stack
            # is last-in-first-out, so push them reversed.
            for child in reversed(list(current)):
                tail = Markup._collapse(child.tail or "")
                if tail:
                    stack.append((None, f"{path}: {tail}"))
                stack.append((child, path))

    @staticmethod
    def loose_text(markup: str) -> str:
        """Fallback for XML that can't be parsed strictly: its text with tags stripped."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(markup, "html.parser")
        return Markup._normalize(soup.get_text("\n"))

    # --- shared --------------------------------------------------------------------

    @staticmethod
    def _collapse(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize(text: str) -> str:
        lines = (Markup._collapse(line) for line in text.splitlines())
        return "\n".join(line for line in lines if line)
