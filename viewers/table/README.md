# @vethuq/table-viewer

A read-only table for large data (VethuQ's table preview: CSV, TSV and Parquet files). Like `viewers/text` it lives outside `web/`,
knows nothing about VethuQ or its API, and has no dependency but React (a peer).

```jsx
<TableViewer
  columns={5}
  header={['id', 'name', ...]}                       // or null
  widths={[4, 20, ...]}                              // a starting width per column, in characters
  total={1_000_000}                                  // rows in the view
  loadRows={(start, count) => fetchRows(start, count)} // Promise<{rows: string[][], numbers: number[]}>
  target={{ index: 5231, column: 2, text: 'wheat' }}  // scrolls to the row, marks the cell (and the text in it)
  sort={{ column: 1, descending: false }}            // what the data is sorted by, if anything
  onSort={(column, descending) => ...}               // column null clears it
/>
```

- Only the rows in view are in the page; the rest is asked for in chunks of 200 as it is scrolled
  near. The data is sorted and filtered by whoever supplies it: the viewer only shows `total` rows.
- Every row has the same height. Drag the edge of a column header to resize it (or focus the edge and
  press the left and right arrows). Click a header to sort: ascending, descending, off.
- Colours follow the Fluent UI theme variables when the page has them.
