# @vethuq/powerpoint-viewer

A read-only reader for a presentation (PowerPoint, OpenDocument), for VethuQ's PowerPoint preview. Like
the other viewers it lives outside `web/`, knows nothing about VethuQ or its API, and has no
dependency but React (a peer).

```jsx
<PowerPointViewer
  deck={{
    slides: [{ n: 1, items: [{ kind: 'title', level: 0, lines: [{ text: 'Review', start: 0 }] }, ...] }],
    first: 0,                         // slides before these
    total: 120,                       // slides in the presentation
    outline: [{ n: 1, title: 'Review' }, ...],                       // every slide
    notes: [{ text: 'A comment', start: 60 }],                       // text the slides lack
  }}
  match={{ start: 7, end: 12 }}       // offsets in the indexed text: finds and marks the words
  onNavigate={({ first }) => ...}     // slides from another one (counting from 0)
  onLocated={(place) => ...}          // 'slide 3', 'note' or null
/>
```

- An item's `kind` is `title`, `subtitle`, `text`, `list` (with a `level`), `row` (a table row, its
  cells joined by a tab) or `note` (speaker notes, shown under the slide's own text). Runs of list
  items become a list and runs of rows a table. An item may have several `lines`, each with its
  `start`, its offset in the text the presentation was indexed as.
- The slide the match is in is outlined and scrolled to, and the matched words marked.
- Whoever supplies the deck gives a window of slides (`first`, `total`) and an outline of all of
  them; clicking a slide in the outline scrolls to it, or asks for it with `onNavigate`.
- Slides are laid out for reading, not as drawn: there are no pictures, positions or fonts.
- Colours follow the Fluent UI theme variables when the page has them.
