"""A feed made into the lines and entries the preview shows, the lines the index kept."""

# ruff: noqa: E501 - sample feeds are written as feeds are
from __future__ import annotations

import pytest

from vethuq_api import feed_view

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Dev Blog</title>
  <link>https://example.com/</link>
  <description>Notes on building things</description>
  <language>en-gb</language>
  <lastBuildDate>Tue, 14 Oct 2026 10:00:00 GMT</lastBuildDate>
  <item>
    <title>First post</title>
    <link>https://example.com/1</link>
    <dc:creator>Ada Lovelace</dc:creator>
    <pubDate>Mon, 13 Oct 2026 09:00:00 GMT</pubDate>
    <category>python</category><category>feeds</category>
    <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt; &amp;amp; friends&lt;/p&gt;&lt;p&gt;Second para&lt;/p&gt;</description>
  </item>
  <item>
    <title>Second post</title>
    <description><![CDATA[<div>In <a href="x">CDATA</a><img src="p.png" alt="a chart"/></div>]]></description>
    <content:encoded><![CDATA[<p>Full content wins</p>]]></content:encoded>
  </item>
</channel>
</rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="de">
  <title>Atom Feed</title>
  <subtitle>A <b>subtitle</b></subtitle>
  <updated>2026-10-14T10:00:00Z</updated>
  <entry>
    <title>Entry one</title>
    <link rel="self" href="https://example.com/self"/>
    <link rel="alternate" href="https://example.com/e1"/>
    <author><name>Grace Hopper</name></author>
    <published>2026-10-13T09:00:00Z</published>
    <updated>2026-10-14T09:00:00Z</updated>
    <category term="compilers" label="Compilers"/>
    <summary>Short summary</summary>
    <content type="html">&lt;p&gt;Long &lt;i&gt;html&lt;/i&gt; content&lt;/p&gt;</content>
  </entry>
  <entry>
    <title type="text">a &lt; b</title>
    <summary type="text">1 &lt; 2 and 3 &gt; 2</summary>
  </entry>
  <entry>
    <title>Xhtml</title>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Inline <em>xhtml</em></p></div></content>
  </entry>
</feed>"""

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com/"><title>RDF Feed</title>
    <description>Old style</description></channel>
  <item rdf:about="https://example.com/1"><title>RDF item</title>
    <link>https://example.com/1</link><dc:date>2026-10-01</dc:date>
    <description>RDF body</description></item>
</rdf:RDF>"""


BROKEN = (
    "<rss><channel><title>Loose &amp; feed</title>"
    "<item><title>Fish & Chips</title><link>https://example.com/f</link>"
    "<category>food</category><category>uk</category>"
    "<description>&lt;p&gt;Tasty&lt;/p&gt; & hot</description></item>"
    "<item><title>Unclosed</title><description>x</description>"
)
ENTITIES = (
    '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;&a;">]>'
    "<rss><channel><title>&b;</title><item><title>safe</title></item></channel></rss>"
)
CASES = {"rss": RSS, "atom": ATOM, "rdf": RDF, "broken": BROKEN, "entities": ENTITIES}


def write(tmp_path, content, name="a.rss"):
    path = tmp_path / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return str(path)


def indexed(feed):
    """The page text the index keeps for a feed read this way."""
    lines = [t for _, t in feed["head"]] + [t for e in feed["entries"] for _, t in e]
    return "\n".join(lines)


class TestRead:
    def test_an_rss_feed_is_its_head_then_each_entry_with_kinds(self, tmp_path):
        feed = feed_view.read(write(tmp_path, RSS))
        assert feed["format"] == "rss" and feed["well_formed"] is True
        assert feed["head"] == [("title", "Dev Blog"), ("description", "Notes on building things")]
        first, second = feed["entries"]
        assert first[:4] == [
            ("title", "First post"),
            ("author", "Author: Ada Lovelace"),
            ("published", "Published: Mon, 13 Oct 2026 09:00:00 GMT"),
            ("categories", "Categories: python, feeds"),
        ]
        assert first[4] == ("link", "Link: https://example.com/1")
        assert first[5:] == [("text", "Hello world & friends"), ("text", "Second para")]
        assert second == [("title", "Second post"), ("text", "Full content wins")]

    def test_atom_and_rdf(self, tmp_path):
        atom = feed_view.read(write(tmp_path, ATOM, "a.atom"))
        assert atom["format"] == "atom" and atom["language"] == "de" and len(atom["entries"]) == 3
        rdf = feed_view.read(write(tmp_path, RDF))
        assert rdf["format"] == "rdf" and rdf["entries"][0][0] == ("title", "RDF item")

    def test_a_feed_that_is_not_well_formed_is_read_loosely(self, tmp_path):
        feed = feed_view.read(write(tmp_path, BROKEN))
        assert feed["well_formed"] is False
        assert feed["head"][0] == ("title", "Loose & feed")
        assert ("categories", "Categories: food, uk") in feed["entries"][0]

    def test_entities_are_never_expanded(self, tmp_path):
        feed = feed_view.read(write(tmp_path, ENTITIES))
        assert feed["well_formed"] is False and "lol" not in indexed(feed)

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"words",
            b"<html><body>x</body></html>",
            b"<a><b/></a>",
            b"<rss><x/></rss>",
            b"\x00\x01",
        ],
    )
    def test_what_is_not_a_feed_is_a_readable_error(self, tmp_path, data):
        with pytest.raises(ValueError, match="cannot be read"):
            feed_view.read(write(tmp_path, data))

    def test_a_feed_that_is_too_large_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(feed_view, "MAX_BYTES", 50)
        with pytest.raises(ValueError, match="too large"):
            feed_view.read(write(tmp_path, RSS))

    def test_every_cut_is_a_feed_or_a_readable_error(self, tmp_path):
        data = ATOM.encode()
        for cut in range(0, len(data), 7):
            try:
                feed_view.read(write(tmp_path, data[:cut]))
            except ValueError as error:
                assert "cannot be read" in str(error)


class TestWindow:
    def test_each_line_knows_where_it_starts_in_the_indexed_text(self, tmp_path):
        feed = feed_view.read(write(tmp_path, RSS))
        text = indexed(feed)
        shown = feed_view.window(feed, None)
        lines = shown["head"] + [line for e in shown["entries"] for line in e["lines"]]
        for line in lines:
            assert text[line["start"] : line["start"] + len(line["text"])] == line["text"]
        assert (shown["first"], shown["total"]) == (0, 2)

    def test_the_window_is_placed_around_the_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(feed_view, "MAX_ENTRIES", 8)
        items = "".join(f"<item><title>entry {n}</title></item>" for n in range(100))
        feed = feed_view.read(
            write(tmp_path, f"<rss><channel><title>T</title>{items}</channel></rss>")
        )
        text = indexed(feed)
        at = text.index("entry 60")
        shown = feed_view.window(feed, at)
        titles = [e["lines"][0]["text"] for e in shown["entries"]]
        assert len(titles) == 8 and "entry 60" in titles and shown["total"] == 100
        assert 0 < shown["first"] <= 60
        assert feed_view.window(feed, 10**9)["first"] == 92  # past the end: the last window

    def test_the_cache_serves_the_same_feed_until_the_file_changes(self, tmp_path):
        path = write(tmp_path, RSS)
        cache = feed_view.Cache()
        assert cache.get(path) is cache.get(path)
        first = cache.get(path)
        write(tmp_path, RSS.replace("Dev Blog", "Other Blog"))
        assert cache.get(path) is not first


class TestTheLinesAreTheOnesTheAddOnIndexes:
    """The preview marks a match by its offset in the indexed text, so the lines must be the
    add-on's, one for one. Needs the RSS add-on, so it is skipped without it."""

    @pytest.mark.parametrize("name", list(CASES))
    def test_the_same_text(self, tmp_path, name):
        reader = pytest.importorskip("vethuq_addon_rss.reader")
        path = write(tmp_path, CASES[name], "a.atom" if name == "atom" else "a.rss")
        (page,) = list(reader.RssReader().read(path))
        feed = feed_view.read(path)
        assert indexed(feed) == page.native_text
        assert feed["well_formed"] is page.details["well_formed"]
        assert len(feed["entries"]) == page.details["item_count"]
