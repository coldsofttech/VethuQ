# @vethuq/code-viewer

A read-only view of source code and structured text for VethuQ's code preview: CSS, JavaScript, JSON,
NDJSON, YAML, TOML, INI, SQL, reStructuredText, log and XML. Like the other viewers it lives outside `web/`, knows nothing about
VethuQ or its API, and has no dependency but React and `@vethuq/text-viewer` (peers).

```jsx
<CodeViewer
  text={source}                                        // the file's text
  language="json"                                      // a key of LANGUAGES
  mode="source"                                        // or "formatted": laid out (for a minified file)
  match={{ before: '...', matched: 'wheat', after: '...' }} // found in the text shown, and marked on its line
  dark={false}                                         // Dark+ instead of Light+
  onLocated={(where) => ...}                           // {line, column, offset, end}, or null: not there
/>
```

- Line numbers and the colours of VS Code's Dark+ and Light+ themes, drawn by `@vethuq/text-viewer`
  (only the lines in view are in the page).
- `codeMode(language, text, longestLine, choice)` says how a file should open: a file with a very
  long line opens `formatted` when its language has a layout, unless the person chose; `canFormat`
  and `tooBig` tell the caller whether to offer the switch.
- `LANGUAGES` has, for each language, its `label`, its `Highlighter`, its `format` (or null) and a
  `hint` that finds a value under its key, for a file the index flattened to `path: value` lines
  (`keyBefore`).
