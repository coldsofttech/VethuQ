import { useEffect, useMemo, useRef } from 'react';

const css = {
  root: {
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
    padding: 12,
    background: 'var(--colorNeutralBackground2, #fafafa)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  paper: {
    boxSizing: 'border-box',
    maxWidth: 820,
    margin: '0 auto',
    padding: '24px 32px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    fontSize: 14,
    lineHeight: 1.5,
    borderRadius: 6,
    border: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  more: { fontSize: 12, color: 'var(--colorNeutralForeground3, #707070)' },
  text: { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  title: { margin: 0, fontSize: 28, fontWeight: 600, overflowWrap: 'anywhere' },
  list: { margin: 0, paddingLeft: 24 },
  item: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  table: { borderCollapse: 'collapse', width: '100%' },
  cell: {
    padding: '4px 8px',
    verticalAlign: 'top',
    border: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
  current: { outline: '2px solid var(--colorBrandStroke1, #0f6cbd)', outlineOffset: 2 },
  mark: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
    color: 'inherit',
  },
};

const HEADING_SIZES = [0, 24, 20, 17, 15, 14, 14];

/** The part of a block from `lo` to `hi` (a table cell of a row): its text, where it starts in the
 * indexed text and the formatting that falls in it. */
function cut(block, lo, hi) {
  const spans = (block.spans ?? [])
    .filter((s) => s.end > lo && s.start < hi)
    .map((s) => ({ ...s, start: Math.max(s.start, lo) - lo, end: Math.min(s.end, hi) - lo }));
  return { ...block, text: block.text.slice(lo, hi), start: block.start + lo, spans };
}

/** The inline style of a stretch of text: what its formatting says. */
function look(span) {
  const style = {};
  if (span.b) style.fontWeight = 700;
  if (span.i) style.fontStyle = 'italic';
  const lines = [span.u && 'underline', span.s && 'line-through'].filter(Boolean);
  if (lines.length) style.textDecoration = lines.join(' ');
  if (span.size) style.fontSize = `${span.size}em`;
  if (span.color) style.color = span.color;
  if (span.pos === 'super') Object.assign(style, { verticalAlign: 'super', fontSize: '0.75em' });
  if (span.pos === 'sub') Object.assign(style, { verticalAlign: 'sub', fontSize: '0.75em' });
  return style;
}

/** The blocks as the things a document is made of: runs of list items are a list, runs of cells or
 * rows are a table, and a heading, a title or a paragraph stands alone. */
function group(blocks) {
  const groups = [];
  blocks.forEach((block, index) => {
    const last = groups[groups.length - 1];
    if (block.kind === 'list') {
      if (last?.type === 'list') last.items.push({ block, index });
      else groups.push({ type: 'list', items: [{ block, index }] });
    } else if (block.kind === 'cell' || block.kind === 'row') {
      const rows = last?.type === 'table' ? last.rows : null;
      const row = rows?.[rows.length - 1];
      if (block.kind === 'row') {
        const cells = [];
        const sep = block.sep ?? '\t';
        const pieces = block.text.split(sep);
        // A row that ends in its separator (RTF's `a|b|`) has no cell after it.
        if (pieces.length > 1 && pieces[pieces.length - 1] === '') pieces.pop();
        let from = 0;
        for (const piece of pieces) {
          cells.push([{ block: cut(block, from, from + piece.length), index }]);
          from += piece.length + sep.length;
        }
        const made = { key: `r${index}`, cells };
        if (rows) rows.push(made);
        else groups.push({ type: 'table', rows: [made] });
      } else {
        const entry = { block, index };
        if (row && row.key === `d${block.row}`) {
          const cell = row.cells[row.cells.length - 1];
          if (row.last === block.cell) cell.push(entry);
          else {
            row.cells.push([entry]);
            row.last = block.cell;
          }
        } else {
          const made = { key: `d${block.row}`, cells: [[entry]], last: block.cell };
          if (rows) rows.push(made);
          else groups.push({ type: 'table', rows: [made] });
        }
      }
    } else groups.push({ type: block.kind, block, index });
  });
  return groups;
}

/**
 * A read-only reader for a word-processor document: its paragraphs as a page, with headings, lists
 * and tables where the file says so. Each block carries its `start`, its offset in the text the
 * document was indexed as (the lines joined by a newline), which is how a match in that text is
 * found and marked. The block the match is in is outlined and scrolled to.
 *
 * @param {object} props
 * @param {object} props.document
 * @param {Array<{kind: string, text: string, start: number, level?: number, row?: number,
 *   cell?: number, sep?: string, align?: string, spans?: Array<object>}>} props.document.blocks
 *   `kind` is `text`, `title`, `heading` (with a `level`), `list` (with a `level`), `cell` (with its
 *   `row` and `cell`) or `row` (cells joined by `sep`, a tab if none). `align` is `center`, `right`
 *   or `justify`. `spans` is the formatting: `{start, end, b, i, u, s, size, color, pos}`, the
 *   offsets in the block's text, `size` a multiple of the usual size, `pos` `super` or `sub`.
 * @param {number} props.document.first How many blocks come before the first one shown.
 * @param {number} props.document.total How many blocks the document has.
 * @param {{start: number, end: number} | null} [props.match] The match, as offsets in the indexed text.
 * @param {(line: number | null) => void} [props.onLocated] Called with the number (from 1) of the
 *   block the match is in, or null if it is in none of those shown.
 */
export function WordViewer({ document, match = null, onLocated }) {
  const marked = useRef(null);
  const target = match ?? { start: -1, end: -1 };
  const { blocks } = document;

  const current = useMemo(() => {
    const at = blocks.findIndex(
      (b) => target.start < b.start + b.text.length && target.end > b.start,
    );
    return at < 0 ? null : at;
  }, [blocks, target.start, target.end]);

  useEffect(() => {
    onLocated?.(current === null ? null : document.first + current + 1);
  }, [current, document.first, onLocated]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center' });
  }, [document, target.start]);

  // A block's text as pieces: each is a stretch with one formatting and either marked or not.
  const shown = (block) => {
    const text = block.text;
    const lo = Math.max(target.start, block.start) - block.start;
    const hi = Math.min(target.end, block.start + text.length) - block.start;
    const hit = hi > lo;
    const spans = block.spans ?? [];
    if (!hit && spans.length === 0) return text;
    const cuts = new Set([0, text.length]);
    for (const s of spans) {
      cuts.add(Math.min(s.start, text.length));
      cuts.add(Math.min(s.end, text.length));
    }
    if (hit) {
      cuts.add(lo);
      cuts.add(hi);
    }
    const points = [...cuts].sort((x, y) => x - y);
    let first = true;
    return points.slice(0, -1).map((from, i) => {
      const to = points[i + 1];
      const piece = text.slice(from, to);
      const span = spans.find((s) => s.start <= from && s.end >= to);
      const style = span ? look(span) : null;
      const inside = hit && from >= lo && to <= hi;
      if (inside) {
        const ref = first ? marked : undefined;
        first = false;
        return (
          <mark key={from} style={{ ...css.mark, ...style }} ref={ref}>
            {piece}
          </mark>
        );
      }
      return style ? (
        <span key={from} style={style}>
          {piece}
        </span>
      ) : (
        piece
      );
    });
  };
  const flag = (index) => (index === current ? { 'aria-current': 'true' } : {});
  const outline = (index, style) => (index === current ? { ...style, ...css.current } : style);

  const later = document.total - document.first - blocks.length;
  return (
    <div style={css.root} role="region" aria-label="Document">
      <div style={css.paper}>
        {document.first > 0 && (
          <span style={css.more}>{document.first} earlier lines not shown.</span>
        )}
        {blocks.length === 0 && <span style={css.more}>This document has no text.</span>}
        {group(blocks).map((g, i) => {
          if (g.type === 'list') {
            return (
              <ul key={i} style={css.list}>
                {g.items.map(({ block, index }) => (
                  <li
                    key={index}
                    style={outline(index, {
                      ...css.item,
                      marginLeft: (block.level ?? 0) * 20,
                      textAlign: block.align,
                    })}
                    {...flag(index)}
                  >
                    {shown(block)}
                  </li>
                ))}
              </ul>
            );
          }
          if (g.type === 'table') {
            return (
              <table key={i} style={css.table}>
                <tbody>
                  {g.rows.map((row) => (
                    <tr key={row.key}>
                      {row.cells.map((cell, j) => (
                        <td key={j} style={css.cell}>
                          {cell.map(({ block, index }) => (
                            <div
                              key={index}
                              style={outline(index, { textAlign: block.align })}
                              {...flag(index)}
                            >
                              {shown(block)}
                            </div>
                          ))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            );
          }
          const { block, index } = g;
          if (block.kind === 'heading') {
            const level = Math.min(Math.max(block.level ?? 1, 1), 6);
            return (
              <div
                key={i}
                role="heading"
                aria-level={level}
                style={outline(index, {
                  ...css.text,
                  fontSize: HEADING_SIZES[level],
                  fontWeight: 600,
                  marginTop: 8,
                  textAlign: block.align,
                })}
                {...flag(index)}
              >
                {shown(block)}
              </div>
            );
          }
          return (
            <p
              key={i}
              style={outline(index, {
                ...(block.kind === 'title' ? css.title : css.text),
                textAlign: block.align,
              })}
              {...flag(index)}
            >
              {shown(block)}
            </p>
          );
        })}
        {later > 0 && <span style={css.more}>{later} later lines not shown.</span>}
      </div>
    </div>
  );
}
