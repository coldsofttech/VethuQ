# @vethuq/html-viewer

A read-only view of a web page, rendered by the browser itself in a sandboxed frame, for VethuQ's
search preview. It lives outside `web/`, like the other viewers.

```jsx
<HtmlViewer
  html={source}                                       // the page's markup
  target={{ before: '...', matched: 'wheat', after: '...' }} // scrolls to these words and marks them
  onMarked={(found) => ...}                           // false: they are not in what the page shows
/>
```

- **Nothing runs and nothing is fetched.** The frame is `sandbox="allow-same-origin"` without
  `allow-scripts`, `allow-forms`, `allow-popups` or `allow-top-navigation`, so scripts never run,
  forms and popups are blocked, and a link does nothing. The frame inherits the page's
  Content-Security-Policy, which keeps remote images, styles and fonts out. A `<meta
http-equiv="refresh">` and a `<base>` are taken out before it is shown.
- **`allow-same-origin` is what lets the viewer mark the words** (it reaches into the frame's
  document). It is safe only because no script can run in it: do not add `allow-scripts`.
- Pictures and stylesheets next to the file are not loaded (the frame has no base address), so a
  page can look plainer than it does in a browser.
- The words are looked for in the page's visible text (not in scripts, styles or the title).
- Peer dependency on `@vethuq/markdown-viewer` for the marking code.
