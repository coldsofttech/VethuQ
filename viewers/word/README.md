# @vethuq/word-viewer

A read-only reader for a word-processor document (Word, RTF, OpenDocument text), for VethuQ's Word
preview. Like the other viewers it lives outside `web/`, knows nothing about VethuQ or its API, and
has no dependency but React (a peer).

```jsx
<WordViewer
  document={{
    blocks: [
      { kind: 'title', text: 'Report', start: 0 },
      { kind: 'heading', text: 'Summary', start: 7, level: 2 },
      { kind: 'list', text: 'One', start: 26, level: 0 },
      { kind: 'cell', text: 'Region', start: 34, row: 1, cell: 1 },
      ...
    ],
    first: 0,                         // blocks before these
    total: 120,                       // blocks in the document
  }}
  match={{ start: 15, end: 20 }}      // offsets in the indexed text: finds and marks the words
  onLocated={(line) => ...}           // the block (from 1) the match is in, or null
/>
```

- A block's `kind` is `text`, `title`, `heading` (with a `level`), `list` (with a `level`), `cell`
  (with the `row` and `cell` it is in) or `row` (a table row, its cells joined by a tab). Runs of
  list items become a list and runs of cells or rows a table.
- A block may carry `align` (`center`, `right`, `justify`) and `spans`, its formatting:
  `{ start, end, b, i, u, s, size, color, pos }` (offsets in the block's text; `size` a multiple of
  the usual size, `pos` `super` or `sub`). A match is marked across a change of formatting, and the
  marked words keep their formatting. A `row` joins its cells by `sep` (a tab if none).
- A block's `start` is where it begins in the text the document was indexed as (the lines joined by
  a newline). The block the match is in is outlined and scrolled to, and the matched words marked,
  also inside a table cell.
- Whoever supplies the document gives a window of it (`first`, `total`); the viewer says how many
  lines come before and after the ones shown.
- Colours follow the Fluent UI theme variables when the page has them.
