import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

/** Rows are fetched in chunks of this many, so scrolling asks for few, large requests. */
export const CHUNK = 200;
const OVERSCAN = 10;
const NUMBER_WIDTH = 64;
const MIN_WIDTH = 40;
const MAX_WIDTH = 800;

const css = {
  root: {
    position: 'relative',
    height: '100%',
    overflow: 'auto',
    fontSize: 13,
    background: 'var(--colorNeutralBackground1, #fff)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  head: {
    position: 'sticky',
    top: 0,
    zIndex: 2,
    display: 'flex',
    background: 'var(--colorNeutralBackground3, #f5f5f5)',
    borderBottom: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
    fontWeight: 600,
  },
  number: {
    flex: '0 0 auto',
    boxSizing: 'border-box',
    width: NUMBER_WIDTH,
    padding: '0 8px',
    textAlign: 'right',
    color: 'var(--colorNeutralForeground3, #707070)',
    userSelect: 'none',
  },
  cell: {
    flex: '0 0 auto',
    boxSizing: 'border-box',
    padding: '0 8px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    borderRight: '1px solid var(--colorNeutralStroke3, #ebebeb)',
  },
  headCell: { position: 'relative', display: 'flex', alignItems: 'center' },
  sortButton: {
    all: 'unset',
    flex: 1,
    minWidth: 0,
    cursor: 'pointer',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  grip: {
    position: 'absolute',
    top: 0,
    right: -3,
    bottom: 0,
    width: 7,
    cursor: 'col-resize',
    zIndex: 1,
    touchAction: 'none',
  },
  hit: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
  },
};

const pixels = (chars) => Math.min(320, Math.max(80, Math.round(chars * 8 + 24)));

/** A cell, with `text` marked in it (ignoring case) when it is the target. */
function Cell({ value, width, hit, text }) {
  let content = value;
  if (hit && text) {
    const at = value.toLowerCase().indexOf(text.toLowerCase());
    if (at >= 0)
      content = (
        <>
          {value.slice(0, at)}
          <mark style={css.hit}>{value.slice(at, at + text.length)}</mark>
          {value.slice(at + text.length)}
        </>
      );
  }
  return (
    <span
      role="cell"
      title={value}
      style={{
        ...css.cell,
        width,
        background: hit ? 'rgba(255, 196, 0, 0.18)' : undefined,
      }}
    >
      {content}
    </span>
  );
}

/**
 * A read-only table of a large data set: only the rows in view are in the page, and `loadRows` is
 * asked for the rest in chunks as they scroll near. Columns can be resized and sorted.
 *
 * @param {object} props
 * @param {number} props.columns
 * @param {string[] | null} [props.header]
 * @param {number[]} [props.widths] A starting width for each column, in characters.
 * @param {number} props.total How many rows the view has.
 * @param {(start: number, count: number) => Promise<{rows: string[][], numbers: number[]}>} props.loadRows
 * @param {{index: number, column?: number | null, text?: string}} [props.target] The row to scroll
 *   to, the cell to mark in it, and the text to mark in that cell.
 * @param {{column: number, descending: boolean} | null} [props.sort]
 * @param {(column: number | null, descending: boolean) => void} [props.onSort]
 * @param {number} [props.rowHeight]
 * @param {string} [props.label]
 */
export function TableViewer({
  columns,
  header = null,
  widths,
  total,
  loadRows,
  target,
  sort = null,
  onSort,
  rowHeight = 28,
  label = 'Table',
}) {
  const root = useRef(null);
  const [sizes, setSizes] = useState(() =>
    Array.from({ length: columns }, (_, c) => pixels(widths?.[c] ?? 12)),
  );
  const [chunks, setChunks] = useState(() => new Map());
  const asked = useRef(new Set());
  const [view, setView] = useState({ top: 0, height: 0 });
  const [failure, setFailure] = useState(null);

  // Other rows (a sort, a filter) start again.
  const source = useRef(loadRows);
  useEffect(() => {
    if (source.current === loadRows) return;
    source.current = loadRows;
    asked.current = new Set();
    setChunks(new Map());
    setFailure(null);
  }, [loadRows]);

  const measure = useCallback(() => {
    const element = root.current;
    if (element) setView({ top: element.scrollTop, height: element.clientHeight });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = root.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  const first = Math.max(0, Math.floor(view.top / rowHeight) - OVERSCAN);
  const last = Math.min(total - 1, Math.ceil((view.top + view.height) / rowHeight) + OVERSCAN);

  useEffect(() => {
    if (total <= 0 || last < first || !view.height) return;
    // A scroll is under way: the view will be measured again.
    if (root.current && Math.abs(root.current.scrollTop - view.top) > 1) return;
    for (let chunk = Math.floor(first / CHUNK); chunk <= Math.floor(last / CHUNK); chunk++) {
      if (asked.current.has(chunk)) continue;
      asked.current.add(chunk);
      const load = loadRows;
      load(chunk * CHUNK, CHUNK).then(
        (data) => {
          if (source.current !== load) return;
          setChunks((current) => new Map(current).set(chunk, data));
        },
        (error) => {
          if (source.current !== load) return;
          asked.current.delete(chunk);
          setFailure(error);
        },
      );
    }
  }, [first, last, total, loadRows, view.top, view.height]);

  // Scroll so the target row is in the middle of the view (below the header).
  const scrolled = useRef(null);
  useLayoutEffect(() => {
    const element = root.current;
    if (!target || target.index == null || !element || !view.height) return;
    const key = `${target.index}:${target.column ?? ''}`;
    if (scrolled.current === key) return;
    scrolled.current = key;
    element.scrollTop = Math.max(0, target.index * rowHeight - (view.height - rowHeight) / 2);
    measure();
  }, [target, view.height, rowHeight, measure]);

  const resize = (column, width) =>
    setSizes((current) =>
      current.map((w, c) => (c === column ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width)) : w)),
    );

  const startDrag = (column) => (event) => {
    event.preventDefault();
    const origin = event.clientX;
    const width = sizes[column];
    const move = (e) => resize(column, width + e.clientX - origin);
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  };

  const sortBy = (column) => {
    if (!onSort) return;
    if (!sort || sort.column !== column) onSort(column, false);
    else if (!sort.descending) onSort(column, true);
    else onSort(null, false);
  };

  const sum = sizes.reduce((a, b) => a + b, 0);
  const width = NUMBER_WIDTH + sum;

  const rows = useMemo(() => {
    const out = [];
    for (let index = first; index <= last; index++) {
      const data = chunks.get(Math.floor(index / CHUNK));
      const row = data?.rows[index % CHUNK];
      if (!row) continue;
      const here = target?.index === index;
      out.push(
        <div
          key={index}
          role="row"
          data-index={index}
          style={{
            position: 'absolute',
            top: index * rowHeight,
            height: rowHeight,
            lineHeight: `${rowHeight}px`,
            width,
            display: 'flex',
            borderBottom: '1px solid var(--colorNeutralStroke3, #ebebeb)',
            background: here ? 'var(--colorNeutralBackground1Hover, #f5f5f5)' : undefined,
          }}
        >
          <span
            style={{ ...css.number, ...{ background: 'var(--colorNeutralBackground2, #fafafa)' } }}
          >
            {data.numbers[index % CHUNK]}
          </span>
          {sizes.map((w, c) => (
            <Cell
              key={c}
              value={row[c] ?? ''}
              width={w}
              hit={here && target.column === c}
              text={target?.text}
            />
          ))}
        </div>,
      );
    }
    return out;
  }, [chunks, first, last, sizes, target, rowHeight, width]);

  return (
    <div ref={root} role="table" aria-label={label} style={css.root} onScroll={measure}>
      <div
        role="rowgroup"
        style={{ ...css.head, width, height: rowHeight, lineHeight: `${rowHeight}px` }}
      >
        <div role="row" style={{ display: 'flex' }}>
          <span role="columnheader" style={{ ...css.number }} aria-label="Row">
            #
          </span>
          {sizes.map((w, c) => {
            const sorted =
              sort?.column === c ? (sort.descending ? 'descending' : 'ascending') : 'none';
            return (
              <div
                key={c}
                role="columnheader"
                aria-sort={sorted}
                style={{ ...css.cell, ...css.headCell, width: w }}
              >
                <button type="button" style={css.sortButton} onClick={() => sortBy(c)} title="Sort">
                  {header?.[c] || `Column ${c + 1}`}
                  {sorted === 'ascending' ? ' ▲' : sorted === 'descending' ? ' ▼' : ''}
                </button>
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`Resize ${header?.[c] || `column ${c + 1}`}`}
                  aria-valuenow={w}
                  tabIndex={0}
                  style={css.grip}
                  onPointerDown={startDrag(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowLeft') resize(c, w - 10);
                    if (e.key === 'ArrowRight') resize(c, w + 10);
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ position: 'relative', height: total * rowHeight, width }}>{rows}</div>
      {failure && (
        <div role="alert" style={{ position: 'sticky', bottom: 0, left: 0, padding: 8 }}>
          The rows could not be loaded: {failure.message}
        </div>
      )}
    </div>
  );
}
