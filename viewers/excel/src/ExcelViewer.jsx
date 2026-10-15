import { useEffect, useMemo, useRef } from 'react';

const BORDER = '1px solid var(--colorNeutralStroke2, #e0e0e0)';

const css = {
  root: {
    height: '100%',
    boxSizing: 'border-box',
    display: 'flex',
    flexDirection: 'column',
    fontSize: 13,
    background: 'var(--colorNeutralBackground2, #fafafa)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  grid: { flexGrow: 1, minHeight: 0, overflow: 'auto' },
  table: {
    borderCollapse: 'separate',
    borderSpacing: 0,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  corner: {
    position: 'sticky',
    top: 0,
    left: 0,
    zIndex: 3,
    minWidth: 44,
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    borderRight: BORDER,
    borderBottom: BORDER,
  },
  column: {
    position: 'sticky',
    top: 0,
    zIndex: 2,
    padding: '2px 8px',
    fontWeight: 600,
    textAlign: 'center',
    color: 'var(--colorNeutralForeground2, #424242)',
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    borderRight: BORDER,
    borderBottom: BORDER,
  },
  rowNumber: {
    position: 'sticky',
    left: 0,
    zIndex: 1,
    padding: '2px 8px',
    textAlign: 'right',
    fontWeight: 400,
    color: 'var(--colorNeutralForeground3, #707070)',
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    borderRight: BORDER,
    borderBottom: BORDER,
  },
  cell: {
    padding: '2px 8px',
    maxWidth: 280,
    minWidth: 64,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    borderRight: BORDER,
    borderBottom: BORDER,
  },
  number: { textAlign: 'right' },
  current: { outline: '2px solid var(--colorBrandStroke1, #0f6cbd)', outlineOffset: -2 },
  bar: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    padding: '4px 8px',
    borderTop: BORDER,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  tabs: { display: 'flex', gap: 2, overflowX: 'auto' },
  tab: {
    padding: '3px 12px',
    border: 'none',
    borderBottom: '2px solid transparent',
    background: 'transparent',
    color: 'inherit',
    font: 'inherit',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  tabOn: { borderBottomColor: 'var(--colorBrandStroke1, #0f6cbd)', fontWeight: 600 },
  button: {
    padding: '2px 10px',
    font: 'inherit',
    color: 'inherit',
    cursor: 'pointer',
    borderRadius: 4,
    border: BORDER,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  muted: { color: 'var(--colorNeutralForeground3, #707070)' },
  notes: {
    maxHeight: 120,
    overflowY: 'auto',
    padding: '4px 8px',
    borderTop: BORDER,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  note: { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  mark: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
    color: 'inherit',
  },
};

/** A column's letters in a spreadsheet: A, B, ... Z, AA, AB, ... */
export function columnName(index) {
  let name = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  }
  return name;
}

const inside = (text, start, match) => match.start < start + text.length && match.end > start;

/**
 * A read-only reader for a spreadsheet: tabs for its sheets, and the cells of one sheet as a grid
 * with column letters and row numbers, a window of rows at a time. Each cell carries its `s`, its
 * offset in the text the workbook was indexed as, which is how a match in that text is found and
 * marked: the cell is outlined, scrolled to and the matched words marked.
 *
 * @param {object} props
 * @param {object} props.workbook
 * @param {Array<{name: string, name_start: number | null, rows: number, cols: number}>} props.workbook.sheets
 * @param {number} props.workbook.sheet The sheet shown (from 0).
 * @param {number} props.workbook.first How many rows of it come before the first one shown.
 * @param {Array<{r: number, cells: Array<{c: number, t: string, n: boolean, s: number}>}>}
 *   props.workbook.rows The rows shown: `r` the row's number in the sheet (from 1), each cell its
 *   column `c` (from 0), text `t`, whether it is a number `n` and its offset `s`.
 * @param {Array<{text: string, start: number}>} [props.workbook.notes] Text the cells do not hold
 *   (comments, text boxes).
 * @param {boolean} [props.workbook.limited_columns] Some columns are not shown.
 * @param {{start: number, end: number} | null} [props.match] The match, as offsets in the indexed text.
 * @param {(request: {sheet: number, first: number | null}) => void} [props.onNavigate] Called to
 *   show another sheet (`first` null: from its top) or other rows of this one.
 * @param {(place: string | null) => void} [props.onLocated] Called with where the match is (`Sheet1!B3`,
 *   a sheet's name, `note`), or null if it is in none of what is shown.
 */
export function ExcelViewer({ workbook, match = null, onNavigate, onLocated }) {
  const marked = useRef(null);
  const target = match ?? { start: -1, end: -1 };
  const { sheets, sheet, rows, first } = workbook;
  const notes = workbook.notes ?? [];
  const current = sheets[sheet];

  const width = useMemo(() => {
    const widest = rows.reduce((w, row) => Math.max(w, ...row.cells.map((c) => c.c + 1)), 0);
    return Math.max(widest, 1);
  }, [rows]);

  const place = useMemo(() => {
    for (const row of rows) {
      for (const cell of row.cells) {
        if (inside(cell.t, cell.s, target)) {
          return `${current?.name ?? ''}!${columnName(cell.c)}${row.r}`;
        }
      }
    }
    if (current?.name_start != null && inside(current.name, current.name_start, target)) {
      return current.name;
    }
    return notes.some((n) => inside(n.text, n.start, target)) ? 'note' : null;
  }, [rows, current, notes, target.start, target.end]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    onLocated?.(place);
  }, [place, onLocated]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center', inline: 'center' });
  }, [workbook, target.start]);

  const shown = (text, start) => {
    const lo = Math.max(target.start, start) - start;
    const hi = Math.min(target.end, start + text.length) - start;
    if (hi <= lo) return text;
    return (
      <>
        {text.slice(0, lo)}
        <mark style={css.mark} ref={marked}>
          {text.slice(lo, hi)}
        </mark>
        {text.slice(hi)}
      </>
    );
  };

  const total = current?.rows ?? 0;
  const last = first + rows.length;
  const page = rows.length;
  const go = (request) => onNavigate?.(request);

  return (
    <div style={css.root} role="region" aria-label="Spreadsheet">
      <div style={css.grid}>
        {rows.length === 0 ? (
          <p style={{ ...css.muted, padding: 12 }}>This sheet has no cells.</p>
        ) : (
          <table style={css.table} aria-label={current?.name || 'Sheet'}>
            <thead>
              <tr>
                <th style={css.corner} />
                {Array.from({ length: width }, (_, c) => (
                  <th key={c} style={css.column} scope="col">
                    {columnName(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const byColumn = new Map(row.cells.map((c) => [c.c, c]));
                return (
                  <tr key={row.r}>
                    <th style={css.rowNumber} scope="row">
                      {row.r}
                    </th>
                    {Array.from({ length: width }, (_, c) => {
                      const cell = byColumn.get(c);
                      if (!cell) return <td key={c} style={css.cell} />;
                      const hit = inside(cell.t, cell.s, target);
                      return (
                        <td
                          key={c}
                          title={cell.t}
                          aria-current={hit ? 'true' : undefined}
                          style={{
                            ...css.cell,
                            ...(cell.n ? css.number : null),
                            ...(hit ? css.current : null),
                          }}
                        >
                          {shown(cell.t, cell.s)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {notes.length > 0 && (
        <div style={css.notes} aria-label="Other text">
          {notes.map((n) => (
            <p key={n.start} style={css.note}>
              {shown(n.text, n.start)}
            </p>
          ))}
        </div>
      )}
      {(first > 0 || last < total || workbook.limited_columns) && (
        <div style={css.bar}>
          <span style={css.muted}>
            Rows {first + 1}–{last} of {total}
            {workbook.limited_columns ? ' (not all columns shown)' : ''}
          </span>
          <button
            type="button"
            style={css.button}
            disabled={first === 0}
            aria-label="Previous rows"
            onClick={() => go({ sheet, first: Math.max(0, first - page) })}
          >
            Previous
          </button>
          <button
            type="button"
            style={css.button}
            disabled={last >= total}
            aria-label="Next rows"
            onClick={() => go({ sheet, first: last })}
          >
            Next
          </button>
        </div>
      )}
      {sheets.length > 0 && (
        <div style={{ ...css.bar, ...css.tabs }} role="tablist" aria-label="Sheets">
          {sheets.map((one, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={i === sheet}
              style={{ ...css.tab, ...(i === sheet ? css.tabOn : null) }}
              onClick={() => i !== sheet && go({ sheet: i, first: null })}
            >
              {one.name_start != null
                ? shown(one.name, one.name_start)
                : one.name || `Sheet ${i + 1}`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
