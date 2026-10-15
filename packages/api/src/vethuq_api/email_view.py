"""An email message (`.eml` or Outlook `.msg`) made into lines for the email preview.

The preview shows a message the way a mail program would (the headers, the attachments, the body),
but its match has to be found in the text the index kept: the header lines (`From:`, `To:`, ...), a
blank line and the body. So this module reads a message into exactly those lines, each with its
offset in the indexed text (so the match can be marked), and lists the attachments, which the index
leaves out. It reads messages the way the EML and MSG add-ons do and tests hold the two together; it
does not go through the licensed add-ons.
"""

from __future__ import annotations

import os
import struct
import threading
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Any

MAX_BYTES = 256 * 1024 * 1024
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_ATTACHMENTS = 500
MAX_RECIPIENTS = 5000
KEEP_FILES = 2

# (key, label) in the order the headers appear in the indexed text.
HEADERS = (
    ("from", "From"),
    ("to", "To"),
    ("cc", "Cc"),
    ("bcc", "Bcc"),
    ("reply_to", "Reply-To"),
    ("subject", "Subject"),
)


class _HtmlText(HTMLParser):
    """The visible text of an HTML body: no tags, scripts or styles."""

    SKIP = frozenset({"script", "style", "head", "title"})
    BREAKS = frozenset({"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BREAKS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BREAKS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


# ----- an .eml ----------------------------------------------------------------------------------


def _header(message: EmailMessage, name: str) -> str | None:
    try:
        value = message[name]
    except Exception:  # noqa: BLE001 - a malformed header must not lose the whole email
        return None
    if value is None:
        return None
    return " ".join(str(value).split()) or None


def _eml_body(message: EmailMessage) -> str:
    for preference in (("plain",), ("html",)):
        part = message.get_body(preferencelist=preference)
        if part is None or part.is_attachment():
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True)
            content = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
        if preference == ("html",):
            parser = _HtmlText()
            parser.feed(content)
            content = parser.text()
        if content.strip():
            return content.strip()
    return ""


def _eml(data: bytes) -> dict[str, Any]:
    message = BytesParser(policy=policy.default).parsebytes(data)
    if not isinstance(message, EmailMessage) or not any(message.keys()):
        raise ValueError("no headers")
    values = {
        "from": _header(message, "From"),
        "to": _header(message, "To"),
        "cc": _header(message, "Cc"),
        "bcc": _header(message, "Bcc"),
        "reply_to": _header(message, "Reply-To"),
        "subject": _header(message, "Subject"),
    }
    attachments = []
    for part in message.iter_attachments():
        if len(attachments) >= MAX_ATTACHMENTS:
            break
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            payload = None
        attachments.append(
            {
                "name": part.get_filename() or "(unnamed)",
                "type": part.get_content_type(),
                "size": len(payload) if isinstance(payload, bytes) else None,
            }
        )
    return {
        "values": values,
        "date": _header(message, "Date"),
        "message_id": _header(message, "Message-ID"),
        "body": _eml_body(message),
        "attachments": attachments,
    }


# ----- an Outlook .msg --------------------------------------------------------------------------

_PROPERTIES = "__properties_version1.0"
_RECIPIENT = "__recip_version1.0_#"
_ATTACHMENT = "__attach_version1.0_#"


def _stream(ole, path: str) -> bytes | None:
    if not ole.exists(path) or ole.get_size(path) > MAX_STREAM_BYTES:
        return None
    return ole.openstream(path).read()


def _raw_text(ole, prefix: str, tag: int) -> str | None:
    for kind, encoding in (("001F", "utf-16-le"), ("001E", "cp1252")):
        data = _stream(ole, f"{prefix}__substg1.0_{tag:04X}{kind}")
        if data is not None:
            return data.decode(encoding, errors="replace").replace("\x00", "")
    return None


def _text(ole, prefix: str, tag: int) -> str | None:
    value = _raw_text(ole, prefix, tag)
    return " ".join(value.split()) or None if value is not None else None


def _fixed(data: bytes | None, header: int) -> dict[int, bytes]:
    found: dict[int, bytes] = {}
    if data is None:
        return found
    for offset in range(header, len(data) - 15, 16):
        (tag,) = struct.unpack_from("<I", data, offset)
        found[tag] = data[offset + 8 : offset + 16]
    return found


def _filetime(value: bytes | None) -> str | None:
    if value is None or len(value) < 8:
        return None
    (ticks,) = struct.unpack("<Q", value[:8])
    try:
        return (datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10)).isoformat()
    except (OverflowError, ValueError):
        return None


def _address(name: str | None, email: str | None) -> str | None:
    if email and name and name.lower() != email.lower():
        return f"{name} <{email}>"
    return email or name


def _children(ole, prefix: str) -> list[str]:
    return sorted(
        e[0]
        for e in ole.listdir(streams=False, storages=True)
        if len(e) == 1 and e[0].startswith(prefix)
    )


def _msg_recipients(ole) -> dict[int, list[str]]:
    found: dict[int, list[str]] = {}
    for name in _children(ole, _RECIPIENT):
        if sum(map(len, found.values())) >= MAX_RECIPIENTS:
            break
        prefix = f"{name}/"
        props = _fixed(_stream(ole, prefix + _PROPERTIES), 8)
        kind = struct.unpack("<i", props.get(0x0C150003, b"\x01\0\0\0")[:4])[0]
        email = _text(ole, prefix, 0x39FE)
        if not email:
            candidate = _text(ole, prefix, 0x3003)
            email = candidate if candidate and "@" in candidate else None
        person = _address(_text(ole, prefix, 0x3001), email)
        if person:
            found.setdefault(kind, []).append(person)
    return found


def _msg_body(ole) -> str:
    plain = _raw_text(ole, "", 0x1000)
    if plain is not None and plain.strip():
        return plain.replace("\r\n", "\n").replace("\r", "\n").strip()
    markup = None
    data = _stream(ole, "__substg1.0_10130102")
    if data:
        for encoding in ("utf-8", "cp1252"):
            try:
                markup = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    else:
        markup = _raw_text(ole, "", 0x1013)
    if not markup:
        return ""
    parser = _HtmlText()
    parser.feed(markup.replace("\x00", ""))
    return parser.text()


def _msg_attachments(ole) -> list[dict[str, Any]]:
    found = []
    for name in _children(ole, _ATTACHMENT)[:MAX_ATTACHMENTS]:
        prefix = f"{name}/"
        props = _fixed(_stream(ole, prefix + _PROPERTIES), 8)
        size = props.get(0x0E200003)
        data = _stream(ole, f"{prefix}__substg1.0_37010102")
        found.append(
            {
                "name": _text(ole, prefix, 0x3707)
                or _text(ole, prefix, 0x3704)
                or _text(ole, prefix, 0x3001)
                or "(unnamed)",
                "type": _text(ole, prefix, 0x370E),
                "size": struct.unpack("<i", size[:4])[0]
                if size
                else (len(data) if data is not None else None),
            }
        )
    return found


def _msg(path: str) -> dict[str, Any]:
    try:
        import olefile  # noqa: PLC0415 - only for these messages
    except ImportError as error:  # pragma: no cover - the MSG add-on needs olefile
        raise ValueError(
            "olefile is not installed, so an Outlook message cannot be shown here."
        ) from error

    if not olefile.isOleFile(path):
        raise ValueError("not an OLE compound file")
    with olefile.OleFileIO(path) as ole:
        if not ole.exists(_PROPERTIES):
            raise ValueError("no message properties")
        props = _fixed(_stream(ole, _PROPERTIES), 32)
        by_kind = _msg_recipients(ole)
        sender_email = _text(ole, "", 0x5D01)
        if not sender_email:
            candidate = _text(ole, "", 0x0C1F)
            sender_email = candidate if candidate and "@" in candidate else None
        values = {
            "from": _address(_text(ole, "", 0x0C1A), sender_email),
            "to": "; ".join(by_kind.get(1, [])) or _text(ole, "", 0x0E04),
            "cc": "; ".join(by_kind.get(2, [])) or _text(ole, "", 0x0E03),
            "bcc": "; ".join(by_kind.get(3, [])) or _text(ole, "", 0x0E02),
            "reply_to": _text(ole, "", 0x0050),
            "subject": _text(ole, "", 0x0037),
        }
        return {
            "values": values,
            "date": _filetime(props.get(0x00390040) or props.get(0x0E060040)),
            "message_id": _text(ole, "", 0x1035),
            "body": _msg_body(ole),
            "attachments": _msg_attachments(ole),
        }


# ----- laying it out ----------------------------------------------------------------------------


def read(path: str, kind: str) -> dict[str, Any]:
    """The message at `path` (`kind` is `eml` or `msg`) as the lines the index kept, each with
    its offset in that text, plus its attachments. Raises `ValueError` (with a message for the
    person) for a file that is not a message."""
    unreadable = ValueError(
        f"This message cannot be read: it is damaged, or it is not an {kind} message."
    )
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("This message is too large to preview. Open it instead.")
    try:
        if kind == "msg":
            parsed = _msg(path)
        else:
            with open(path, "rb") as handle:
                parsed = _eml(handle.read())
    except ValueError as error:
        if "not installed" in str(error):
            raise
        raise unreadable from error
    except Exception as error:  # noqa: BLE001 - a damaged file is a message, never a server error
        raise unreadable from error
    head: list[tuple[str, str]] = [
        (key, f"{label}: {parsed['values'][key]}")
        for key, label in HEADERS
        if parsed["values"][key]
    ]
    # `Subject` is the last header above; the index puts `Date` and `Message-ID` after it.
    if parsed["date"]:
        head.append(("date", f"Date: {parsed['date']}"))
    if parsed["message_id"]:
        head.append(("message_id", f"Message-ID: {parsed['message_id']}"))
    offset = 0
    head_lines = []
    for key, text in head:
        head_lines.append({"kind": key, "text": text, "start": offset})
        offset += len(text) + 1
    body = parsed["body"]
    if body:
        offset = max(offset - 1, 0) + (2 if head else 0)
    body_lines = []
    for line in body.split("\n") if body else []:
        body_lines.append({"text": line, "start": offset})
        offset += len(line) + 1
    return {
        "kind": kind,
        "head": head_lines,
        "body": body_lines,
        "attachments": parsed["attachments"],
    }


class Cache:
    """The last few messages read, so switching between matches does not read the file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, str, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, path: str, kind: str) -> dict[str, Any]:
        real = os.path.realpath(path)
        stat = os.stat(real)
        key = (kind, real, stat.st_mtime_ns, stat.st_size)
        with self._lock:
            found = self._files.pop(key, None)
            if found is not None:
                self._files[key] = found
                return found
        parsed = read(real, kind)
        with self._lock:
            self._files[key] = parsed
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return parsed
