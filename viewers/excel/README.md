# @vethuq/excel-viewer

A read-only reader for a spreadsheet (Excel, OpenDocument), for VethuQ's Excel preview. Like the other
viewers it lives outside `web/`, knows nothing about VethuQ or its API, and has no dependency but
React (a peer).

```jsx
<ExcelViewer
  workbook={{
    sheets: [{ name: 'Prices', name_start: 0, rows: 1200, cols: 8 }, ...],  // tabs
    sheet: 0,                         // the sheet shown (from 0)
    first: 0,                         // rows of it before these
    rows: [{ r: 1, cells: [{ c: 0, t: 'Region', n: false, s: 7 }, ...] }, ...],
    notes: [{ text: 'A comment', start: 45 }],                              // text the cells lack
    limited_columns: false,
  }}
  match={{ start: 28, end: 30 }}      // offsets in the indexed text: finds and marks the words
  onNavigate={({ sheet, first }) => ...}  // another sheet (first null: from its top) or rows
  onLocated={(place) => ...}          // 'Prices!C4', a sheet's name, 'note' or null
/>
```

- A row's `r` is its number in the sheet (from 1) and a cell's `c` its column (from 0), so a sheet's
  empty rows and cells keep their places. A cell's `s` is where it begins in the text the workbook
  was indexed as; `name_start` is the same for a sheet's name.
- The cell the match is in is outlined and scrolled to, and the matched words marked, whichever
  sheet tab or note holds them.
- Whoever supplies the workbook gives a window of rows of one sheet; the viewer pages with
  `onNavigate`.
- Cells are shown as text, numbers right-aligned; there is no formula bar, formatting or editing.
- Colours follow the Fluent UI theme variables when the page has them.
