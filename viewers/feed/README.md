# @vethuq/feed-viewer

A read-only reader for an RSS or Atom feed, for VethuQ's feed preview. Like the other viewers it lives
outside `web/`, knows nothing about VethuQ or its API, and has no dependency but React (a peer).

```jsx
<FeedViewer
  feed={{
    format: 'rss', language: 'en', updated: '...', well_formed: true,
    head: [{ kind: 'title', text: 'Dev Blog', start: 0 }, ...],          // the feed's own lines
    entries: [{ lines: [{ kind: 'title', text: 'First', start: 15 }, ...] }, ...],
    first: 0,                                                            // entries before these
    total: 120,                                                          // entries in the feed
  }}
  match={{ start: 33, end: 38 }}      // offsets in the indexed text: finds and marks the words
  onLocated={(entry) => ...}          // the entry (from 1) the match is in, or null
/>
```

- A line's `kind` is `title`, `description`, `text`, `author`, `published`, `categories` or `link`;
  its `start` is where it begins in the text the feed was indexed as (the lines joined by a
  newline). The label the index keeps on `author`, `published`, `categories` and `link` lines
  (`Author: `) is not shown; the viewer lays those out itself.
- The entry the match is in is outlined and scrolled to, and the matched words are marked, whichever
  line they are in.
- Only a web address (`http:` or `https:`) is made a link; a feed can say anything.
- Whoever supplies the feed gives a window of it (`first`, `total`); the viewer says how many entries
  come before and after the ones shown.
- Colours follow the Fluent UI theme variables when the page has them.
