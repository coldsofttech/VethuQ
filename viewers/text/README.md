# @vethuq/text-viewer

A read-only viewer for large plain text, used by VethuQ's search preview. It lives outside `web/` so
it stays free of the app: it knows nothing about VethuQ, Fluent UI or the API.

```jsx
<TextViewer
  total={1_200_000} // how many lines there are
  loadLines={(start, count) => fetchLines(start, count)} // Promise<string[]>, 0-based start
  target={{ line: 5231, column: 17, length: 5 }} // scrolls there and marks the words
/>
```

- Only the lines in view (plus a margin) are in the page; the rest is asked for in chunks of 200 as
  it is scrolled near, so a very large file opens at once.
- Every line has the same height (`lineHeight`, 20 px), which is what makes that possible. Lines do
  not wrap: a long one scrolls sideways.
- Colours follow the Fluent UI theme variables when the page has them, and fall back to plain ones.
- No dependency but React (a peer).

It is consumed from `web/` as a local dependency (`"@vethuq/text-viewer": "file:../viewers/text"`),
so Vite compiles it with the app. Its tests run with `web`'s (`npm test` there).
