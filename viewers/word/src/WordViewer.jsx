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
        let from = block.start;
        for (const piece of block.text.split('\t')) {
          cells.push([{ block: { ...block, text: piece, start: from }, index }]);
          from += piece.length + 1;
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
 *   cell?: number}>} props.document.blocks `kind` is `text`, `title`, `heading` (with a `level`),
 *   `list` (with a `level`), `cell` (with its `row` and `cell`) or `row` (cells joined by a tab).
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

  const shown = (block) => {
    const lo = Math.max(target.start, block.start) - block.start;
    const hi = Math.min(target.end, block.start + block.text.length) - block.start;
    if (hi <= lo) return block.text;
    return (
      <>
        {block.text.slice(0, lo)}
        <mark style={css.mark} ref={marked}>
          {block.text.slice(lo, hi)}
        </mark>
        {block.text.slice(hi)}
      </>
    );
  };
  const flag = (index) => (index === current ? { 'aria-current': 'true' } : {});
  const look = (index, style) => (index === current ? { ...style, ...css.current } : style);

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
                    style={look(index, { ...css.item, marginLeft: (block.level ?? 0) * 20 })}
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
                            <div key={index} style={look(index, {})} {...flag(index)}>
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
                style={look(index, {
                  ...css.text,
                  fontSize: HEADING_SIZES[level],
                  fontWeight: 600,
                  marginTop: 8,
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
              style={look(index, block.kind === 'title' ? css.title : css.text)}
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
