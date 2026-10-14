"""A web archive made into one page a sandboxed frame can show."""

from __future__ import annotations

import base64
import html
import quopri
import re
from pathlib import Path

import pytest

from vethuq_api import mhtml_view

FIXTURE = Path(__file__).parent / "fixtures" / "chrome.mhtml"
BOUNDARY = "----MultipartBoundary--tests"
PAGE = "https://example.com/news/harvest"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def part(kind: str, location: str | None, body: bytes, cid: str = "") -> bytes:
    lines = [f"Content-Type: {kind}"]
    if cid:
        lines.append(f"Content-ID: <{cid}>")
    if kind.startswith("text/"):
        lines.append("Content-Transfer-Encoding: quoted-printable")
        encoded = quopri.encodestring(body).replace(b"\n", b"\r\n")
    else:
        lines.append("Content-Transfer-Encoding: base64")
        encoded = base64.encodebytes(body).replace(b"\n", b"\r\n")
    if location:
        lines.append(f"Content-Location: {location}")
    return (
        f"--{BOUNDARY}\r\n".encode()
        + ("\r\n".join(lines) + "\r\n\r\n").encode()
        + encoded
        + b"\r\n"
    )


def archive(markup: str, *others: bytes, location: str | None = PAGE, subject: str = "Harvest"):
    head = (
        f"From: <Saved by Blink>\r\nSnapshot-Content-Location: {location}\r\nSubject: {subject}\r\n"
        f'MIME-Version: 1.0\r\nContent-Type: multipart/related;\r\n\ttype="text/html";\r\n'
        f'\tboundary="{BOUNDARY}"\r\n\r\n'
    ).encode()
    body = part("text/html", location, markup.encode("utf-8")) + b"".join(others)
    return head + body + f"--{BOUNDARY}--\r\n".encode()


def build(tmp_path, markup, *others, **kw):
    path = tmp_path / "a.mhtml"
    path.write_bytes(archive(markup, *others, **kw))
    return mhtml_view.view(mhtml_view.read(str(path)))


def data_of(uri: str) -> bytes:
    return base64.b64decode(uri.split(",", 1)[1])


class TestPictures:
    def test_an_image_becomes_a_data_address(self, tmp_path):
        v = build(
            tmp_path,
            "<img src='chart.png'>",
            part("image/png", f"{PAGE.rsplit('/', 1)[0]}/chart.png", PNG),
        )
        uri = re.search(r'src="(data:[^"]+)"', v["rendered"])[1]
        assert uri.startswith("data:image/png;base64,") and data_of(uri) == PNG

    def test_an_absolute_or_a_root_relative_address_finds_it(self, tmp_path):
        markup = "<img src='https://example.com/news/c.png'><img src='/news/c.png'>"
        v = build(tmp_path, markup, part("image/png", "https://example.com/news/c.png", PNG))
        assert v["rendered"].count("data:image/png;base64,") == 2

    def test_srcset_candidates_each_keep_their_descriptor(self, tmp_path):
        markup = "<img srcset='https://example.com/a.png 1x, https://example.com/b.png 2x'>"
        v = build(
            tmp_path,
            markup,
            part("image/png", "https://example.com/a.png", PNG),
            part("image/png", "https://example.com/b.png", PNG),
        )
        srcset = re.search(r'srcset="([^"]+)"', v["rendered"])[1]
        assert re.fullmatch(r"data:image/png;base64,\S+ 1x, data:image/png;base64,\S+ 2x", srcset)

    def test_a_cid_is_found_by_content_id_and_by_location(self, tmp_path):
        v = build(
            tmp_path,
            "<img src='cid:logo@x'><img src='cid:loc-1'>",
            part("image/png", None, PNG, cid="logo@x"),
            part("image/png", "cid:loc-1", PNG),
        )
        assert v["rendered"].count("data:image/png;base64,") == 2

    def test_a_reference_the_archive_cannot_answer_is_left_as_it_is(self, tmp_path):
        markup = (
            "<img src='https://cdn.example.net/remote.png'><img src='data:image/gif;base64,AAAA'>"
        )
        v = build(tmp_path, markup)
        assert v["rendered"] == markup  # nothing to answer, so nothing changes
        assert v["incomplete"] is False

    def test_a_part_that_is_not_an_image_is_not_put_in_as_one(self, tmp_path):
        v = build(
            tmp_path,
            "<img src='x.png'>",
            part("text/css", "https://example.com/news/x.png", b"a{}"),
        )
        assert "data:" not in v["rendered"]


class TestStyles:
    def test_a_linked_stylesheet_becomes_a_style_block_with_its_urls_inlined(self, tmp_path):
        css = b'.hero { background: url("bg.png"); }'
        v = build(
            tmp_path,
            "<head><link rel='stylesheet' href='site.css'></head><body>x</body>",
            part("text/css", "https://example.com/news/site.css", css),
            part("image/png", "https://example.com/news/bg.png", PNG),
        )
        assert "<link" not in v["rendered"] and "<style>" in v["rendered"]
        assert 'url("data:image/png;base64,' in v["rendered"]

    def test_chromes_cid_stylesheets(self, tmp_path):
        v = build(
            tmp_path,
            '<link rel="stylesheet" type="text/css" href="cid:css-1@mhtml.blink" />',
            part("text/css", "cid:css-1@mhtml.blink", b"p{color:red}"),
        )
        assert "<style>p{color:red}</style>" in v["rendered"]

    def test_an_import_is_put_in_and_a_deep_chain_is_cut(self, tmp_path):
        parts = [
            part(
                "text/css",
                f"https://example.com/news/{n}.css",
                f"@import '{n + 1}.css'; .c{n}{{}}".encode(),
            )
            for n in range(1, 6)
        ]
        v = build(tmp_path, "<link rel='stylesheet' href='1.css'>", *parts)
        assert ".c1{}" in v["rendered"] and ".c2{}" in v["rendered"]
        assert ".c5{}" not in v["rendered"]  # nested imports stop at a depth

    def test_a_style_block_and_a_style_attribute(self, tmp_path):
        markup = (
            "<style>.a{background:url(bg.png)}</style>"
            "<div style=\"background-image: url('bg.png')\">x</div>"
        )
        v = build(tmp_path, markup, part("image/png", "https://example.com/news/bg.png", PNG))
        assert v["rendered"].count("data:image/png;base64,") == 2

    def test_a_sheet_cannot_close_its_own_style_block(self, tmp_path):
        v = build(
            tmp_path,
            "<link rel='stylesheet' href='s.css'><p>ok</p>",
            part("text/css", "https://example.com/news/s.css", b"/* </style><p>injected</p> */"),
        )
        assert "</style><p>injected" not in v["rendered"]


class TestFrames:
    def test_a_saved_frame_is_carried_in_srcdoc(self, tmp_path):
        v = build(
            tmp_path,
            "<p>Main</p><iframe src='cid:frame-1'></iframe>",
            part("text/html", "https://example.com/f", b"<p>Frame says barley</p>", cid="frame-1"),
        )
        srcdoc = html.unescape(re.search(r'srcdoc="([^"]*)"', v["rendered"])[1])
        assert srcdoc == "<p>Frame says barley</p>" and " src=" not in v["rendered"]

    def test_a_frame_has_its_own_pictures_inlined(self, tmp_path):
        v = build(
            tmp_path,
            "<iframe src='https://example.com/f'></iframe>",
            part("text/html", "https://example.com/f", b"<img src='/p.png'>"),
            part("image/png", "https://example.com/p.png", PNG),
        )
        assert "data:image/png;base64," in html.unescape(v["rendered"])

    def test_frames_nest_to_a_depth_and_no_further(self, tmp_path):
        parts = [
            part(
                "text/html",
                f"https://example.com/f{n}",
                f"<p>f{n}</p><iframe src='https://example.com/f{n + 1}'></iframe>".encode(),
            )
            for n in range(1, 8)
        ]
        v = build(tmp_path, "<p>main</p><iframe src='https://example.com/f1'></iframe>", *parts)
        text = v["rendered"]
        for _ in range(mhtml_view.MAX_DEPTH):
            text = html.unescape(text)
        assert "f1" in text and "f2" in text and "<p>f7</p>" not in text

    def test_the_source_has_the_page_then_each_frame_under_a_comment(self, tmp_path):
        v = build(
            tmp_path,
            "<p>Main</p>",
            part("text/html", "https://example.com/f", b"<p>Frame says barley</p>"),
        )
        assert (
            v["text"]
            == "<p>Main</p>\n\n<!-- Frame: https://example.com/f -->\n<p>Frame says barley</p>"
        )
        assert v["frame_count"] == 1


class TestBudget:
    def test_what_does_not_fit_is_left_out_and_said(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mhtml_view, "INLINE_BUDGET", len(PNG) + 5)
        markup = "<img src='https://example.com/a.png'><img src='https://example.com/b.png'>"
        v = build(
            tmp_path,
            markup,
            part("image/png", "https://example.com/a.png", PNG),
            part("image/png", "https://example.com/b.png", PNG),
        )
        assert v["rendered"].count("data:image/png;base64,") == 1 and v["incomplete"] is True

    def test_a_page_that_fits_is_complete(self, tmp_path):
        assert build(tmp_path, "<p>x</p>")["incomplete"] is False


class TestFacts:
    def test_address_subject_and_encoding(self, tmp_path):
        v = build(tmp_path, "<p>x</p>", subject="Harvest notes")
        assert (v["address"], v["subject"], v["encoding"]) == (PAGE, "Harvest notes", "utf-8")

    def test_the_longest_line_is_of_the_source(self, tmp_path):
        assert build(tmp_path, "<p>x</p>\n<p>" + "y" * 50 + "</p>")["longest_line"] == 57


class TestNotAnArchive:
    @pytest.mark.parametrize(
        ("data", "why"),
        [
            (b"", "no MIME headers"),
            (b"plain text\nno headers\n", "no MIME headers"),
            (b"From: a@b.c\r\nContent-Type: text/plain\r\n\r\nhi\r\n", "no HTML page"),
        ],
    )
    def test_it_says_why(self, tmp_path, data, why):
        path = tmp_path / "bad.mhtml"
        path.write_bytes(data)
        with pytest.raises(ValueError, match=why):
            mhtml_view.read(str(path))

    def test_too_many_parts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mhtml_view, "MAX_PARTS", 2)
        path = tmp_path / "a.mhtml"
        path.write_bytes(
            archive("<p>x</p>", *[part("text/css", f"https://e/{n}.css", b"a{}") for n in range(5)])
        )
        with pytest.raises(ValueError, match="too many parts"):
            mhtml_view.read(str(path))

    def test_a_file_over_the_size_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mhtml_view, "MAX_BYTES", 50)
        path = tmp_path / "a.mhtml"
        path.write_bytes(archive("<p>x</p>"))
        with pytest.raises(ValueError, match="too large to preview"):
            mhtml_view.read(str(path))


class TestRealChromeArchive:
    """`fixtures/chrome.mhtml` is what Chromium's `Page.captureSnapshot` wrote for a small page."""

    def view(self):
        return mhtml_view.view(mhtml_view.read(str(FIXTURE)))

    def test_its_picture_stylesheet_and_frame_are_all_put_in(self):
        v = self.view()
        rendered = v["rendered"]
        assert re.search(r'<img src="data:image/png;base64,', rendered)
        assert "<link" not in rendered and '<style>@charset "utf-8";' in rendered
        assert "srcdoc=" in rendered and "Frame says barley" in html.unescape(rendered)
        assert v["incomplete"] is False and v["frame_count"] == 1

    def test_the_picture_is_the_one_in_the_archive(self):
        uri = re.search(r'<img src="(data:image/png;base64,[^"]+)"', self.view()["rendered"])[1]
        assert data_of(uri)[:8] == b"\x89PNG\r\n\x1a\n" and len(data_of(uri)) == 1945

    def test_the_source_is_the_page_as_chrome_wrote_it(self):
        text = self.view()["text"]
        assert 'src="http://127.0.0.1:8765/scan.png"' in text and 'href="cid:css-' in text
        assert "<!-- Frame: http://127.0.0.1:8765/frame.html -->" in text
