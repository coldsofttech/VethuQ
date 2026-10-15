"""An email message made into the lines the preview shows, the lines the index kept."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vethuq_api import email_view

MSG_TESTS = (
    Path(__file__).resolve().parents[3].parent
    / "VethuQ-premium/packages/add-ons/file-types/msg/tests"
)

EML = (
    b"From: Ada Lovelace <ada@example.com>\r\n"
    b"To: Bob <bob@example.com>, carol@example.com\r\n"
    b"Subject: Wheat prices\r\n"
    b"Date: Mon, 13 Oct 2026 09:00:00 +0000\r\n"
    b"Message-ID: <a1@example.com>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
    b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPrices fell\r\nagain today\r\n"
    b"--B\r\nContent-Type: application/pdf; name=report.pdf\r\n"
    b'Content-Disposition: attachment; filename="report.pdf"\r\n'
    b"Content-Transfer-Encoding: base64\r\n\r\nSGVsbG8=\r\n--B--\r\n"
)

HTML_EML = (
    b"From: a@example.com\r\nSubject: Hi\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    b"<html><head><style>p{}</style></head><body><p>Hello <b>world</b></p><p>Bye</p></body></html>"
)


def indexed(message):
    """The text the add-ons index: the header lines, a blank line, the body."""
    head = "\n".join(line["text"] for line in message["head"])
    body = "\n".join(line["text"] for line in message["body"])
    if head and body:
        return f"{head}\n\n{body}"
    return head or body


def write(tmp_path, data, name="a.eml"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def msg_fixtures():
    path = MSG_TESTS / "msg_fixtures.py"
    if not path.exists():
        pytest.skip("the MSG add-on's test fixtures are not next to this checkout")
    pytest.importorskip("olefile")
    spec = importlib.util.spec_from_file_location("msg_fixtures_for_email_view", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestEml:
    def test_headers_attachments_and_body_with_offsets(self, tmp_path):
        message = email_view.read(write(tmp_path, EML), "eml")
        assert [line["kind"] for line in message["head"]] == [
            "from",
            "to",
            "subject",
            "date",
            "message_id",
        ]
        assert message["head"][0] == {
            "kind": "from",
            "text": "From: Ada Lovelace <ada@example.com>",
            "start": 0,
        }
        assert [line["text"] for line in message["body"]] == ["Prices fell\r", "again today"]
        text = indexed(message)
        for line in message["head"] + message["body"]:
            assert text[line["start"] : line["start"] + len(line["text"])] == line["text"]
        assert message["attachments"] == [
            {"name": "report.pdf", "type": "application/pdf", "size": 5}
        ]

    def test_an_html_body_is_the_text_of_it(self, tmp_path):
        message = email_view.read(write(tmp_path, HTML_EML), "eml")
        assert [line["text"] for line in message["body"]] == ["Hello world", "Bye"]
        text = indexed(message)
        assert all(
            text[line["start"] : line["start"] + len(line["text"])] == line["text"]
            for line in message["body"]
        )

    def test_a_body_with_no_headers_starts_at_zero(self, tmp_path):
        message = email_view.read(write(tmp_path, b"X-Thing: 1\r\n\r\nJust text"), "eml")
        assert message["head"] == []
        assert message["body"] == [{"text": "Just text", "start": 0}]

    def test_what_is_not_a_message_says_so(self, tmp_path):
        with pytest.raises(ValueError, match="cannot be read"):
            email_view.read(write(tmp_path, b"\x00\x01 not a message"), "eml")
        with pytest.raises(ValueError, match="cannot be read"):
            email_view.read(write(tmp_path, b"this is not a message", "b.msg"), "msg")

    def test_a_message_over_the_limit_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(email_view, "MAX_BYTES", 10)
        with pytest.raises(ValueError, match="too large"):
            email_view.read(write(tmp_path, EML), "eml")

    def test_the_cache_reads_a_file_once_until_it_changes(self, tmp_path, monkeypatch):
        path = write(tmp_path, EML)
        calls = []
        real = email_view.read
        monkeypatch.setattr(email_view, "read", lambda p, k: calls.append(p) or real(p, k))
        cache = email_view.Cache()
        first = cache.get(path, "eml")
        assert cache.get(path, "eml") is first and len(calls) == 1
        Path(path).write_bytes(EML + b"\r\n")
        cache.get(path, "eml")
        assert len(calls) == 2


class TestMsg:
    def test_the_lines_with_offsets(self, tmp_path):
        fixtures = msg_fixtures()
        path = fixtures.write_msg(
            tmp_path / "a.msg",
            recipients=[(1, "Bob", "bob@example.com"), (2, "Carol", "carol@example.com")],
            sent=datetime(2025, 9, 2, 10, 30, tzinfo=UTC),
        )
        message = email_view.read(str(path), "msg")
        assert [line["text"] for line in message["head"]] == [
            "From: Alice Unal <alice@example.com>",
            "To: Bob <bob@example.com>",
            "Cc: Carol <carol@example.com>",
            "Subject: Budget review",
            "Date: 2025-09-02T10:30:00+00:00",
            "Message-ID: <abc123@example.com>",
        ]
        text = indexed(message)
        for line in message["head"] + message["body"]:
            assert text[line["start"] : line["start"] + len(line["text"])] == line["text"]
        assert [line["text"] for line in message["body"]] == ["Quarterly numbers attached."]


class TestTheLinesAreTheOnesTheAddOnsIndex:
    """The preview marks a match by its offset in the indexed text, so the lines must be the
    add-ons', one for one. Needs the add-ons, so these are skipped without them."""

    def test_eml(self, tmp_path):
        reader = pytest.importorskip("vethuq_addon_eml.reader")
        for data in (EML, HTML_EML):
            path = write(tmp_path, data)
            (page,) = list(reader.EmlReader().read(Path(path)))
            assert indexed(email_view.read(path, "eml")) == page.native_text

    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"body": None, "html": "<p>Hello <b>there</b></p><p>Bye</p>"},
            {"subject": None, "sender_name": None, "sender_smtp": None, "message_id": None},
            {"ansi": True, "display_to": "Dave", "reply_to": "r@example.com"},
        ],
    )
    def test_msg(self, tmp_path, kwargs):
        fixtures = msg_fixtures()
        reader = pytest.importorskip("vethuq_addon_msg.reader")
        path = fixtures.write_msg(tmp_path / "a.msg", **kwargs)
        (page,) = list(reader.MsgReader().read(path))
        assert indexed(email_view.read(str(path), "msg")) == page.native_text
