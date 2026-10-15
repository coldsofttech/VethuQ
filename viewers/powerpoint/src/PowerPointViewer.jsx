import { useEffect, useMemo, useRef } from 'react';

const BORDER = '1px solid var(--colorNeutralStroke2, #e0e0e0)';

const css = {
  root: {
    height: '100%',
    boxSizing: 'border-box',
    display: 'flex',
    fontSize: 14,
    background: 'var(--colorNeutralBackground2, #fafafa)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  outline: {
    flex: '0 0 190px',
    overflowY: 'auto',
    padding: 8,
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    borderRight: BORDER,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  entry: {
    display: 'flex',
    gap: 6,
    padding: '4px 6px',
    textAlign: 'left',
    font: 'inherit',
    fontSize: 12,
    color: 'inherit',
    cursor: 'pointer',
    borderRadius: 4,
    border: '1px solid transparent',
    background: 'transparent',
  },
  entryOn: { borderColor: 'var(--colorBrandStroke1, #0f6cbd)' },
  number: { flexShrink: 0, minWidth: 18, color: 'var(--colorNeutralForeground3, #707070)' },
  entryTitle: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  slides: {
    flexGrow: 1,
    minWidth: 0,
    overflowY: 'auto',
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  more: { fontSize: 12, color: 'var(--colorNeutralForeground3, #707070)' },
  slide: {
    boxSizing: 'border-box',
    aspectRatio: '16 / 9',
    padding: '20px 28px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    borderRadius: 6,
    border: BORDER,
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  current: { outline: '2px solid var(--colorBrandStroke1, #0f6cbd)', outlineOffset: 2 },
  label: { fontSize: 11, color: 'var(--colorNeutralForeground3, #707070)' },
  title: { margin: 0, fontSize: 24, fontWeight: 600, overflowWrap: 'anywhere' },
  subtitle: { margin: 0, fontSize: 16, color: 'var(--colorNeutralForeground2, #424242)' },
  text: { margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  list: { margin: 0, paddingLeft: 22 },
  table: { borderCollapse: 'collapse', width: '100%' },
  cell: {
    padding: '3px 8px',
    verticalAlign: 'top',
    border: BORDER,
    overflowWrap: 'anywhere',
  },
  notes: {
    marginTop: 'auto',
    paddingTop: 6,
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    fontSize: 12,
    color: 'var(--colorNeutralForeground2, #424242)',
    borderTop: BORDER,
  },
  other: { padding: '6px 10px', borderRadius: 6, border: BORDER, fontSize: 12 },
  mark: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
    color: 'inherit',
  },
};

const hits = (line, match) => match.start < line.start + line.text.length && match.end > line.start;

/** The items of a slide as the things a slide is made of: runs of list items are a list and runs of
 * table rows a table; a title, a subtitle, text and speaker notes stand alone. */
function group(items) {
  const groups = [];
  items.forEach((item, index) => {
    const last = groups[groups.length - 1];
    if (item.kind === 'list' && last?.type === 'list') last.items.push({ item, index });
    else if (item.kind === 'list') groups.push({ type: 'list', items: [{ item, index }] });
    else if (item.kind === 'row' && last?.type === 'table') last.items.push({ item, index });
    else if (item.kind === 'row') groups.push({ type: 'table', items: [{ item, index }] });
    else groups.push({ type: item.kind, items: [{ item, index }] });
  });
  return groups;
}

/**
 * A read-only reader for a presentation: an outline of its slides (their numbers and titles) and the
 * slides as cards with their title, text, tables and speaker notes, a window of slides at a time.
 * Each line carries its `start`, its offset in the text the presentation was indexed as, which is how
 * a match in that text is found and marked: the slide is outlined and scrolled to, and the matched
 * words marked.
 *
 * @param {object} props
 * @param {object} props.deck
 * @param {Array<{n: number, items: Array<{kind: string, level: number, lines: Array<{text: string,
 *   start: number}>}>}>} props.deck.slides The slides shown: `n` the slide's number (from 1), each
 *   item `kind` `title`, `subtitle`, `text`, `list` (with a `level`), `row` (cells joined by a tab)
 *   or `note` (speaker notes).
 * @param {number} props.deck.first How many slides come before the first one shown.
 * @param {number} props.deck.total How many slides the presentation has.
 * @param {Array<{n: number, title: string}>} props.deck.outline Every slide's number and title.
 * @param {Array<{text: string, start: number}>} [props.deck.notes] Text the slides do not hold
 *   (comments, SmartArt).
 * @param {{start: number, end: number} | null} [props.match] The match, as offsets in the indexed text.
 * @param {(request: {first: number}) => void} [props.onNavigate] Called to show slides from another
 *   one (`first` counts from 0).
 * @param {(place: string | null) => void} [props.onLocated] Called with where the match is
 *   (`slide 3`, `note`), or null if it is in none of what is shown.
 */
export function PowerPointViewer({ deck, match = null, onNavigate, onLocated }) {
  const marked = useRef(null);
  const slideRefs = useRef(new Map());
  const target = match ?? { start: -1, end: -1 };
  const { slides, first, total, outline } = deck;
  const notes = deck.notes ?? [];

  const current = useMemo(() => {
    const found = slides.find((s) => s.items.some((i) => i.lines.some((l) => hits(l, target))));
    return found ? found.n : null;
  }, [slides, target.start, target.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const place =
    current !== null ? `slide ${current}` : notes.some((n) => hits(n, target)) ? 'note' : null;

  useEffect(() => {
    onLocated?.(place);
  }, [place, onLocated]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center' });
  }, [deck, target.start]);

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
  const lines = (item) =>
    item.lines.map((line, i) => (
      <span key={i}>
        {i > 0 && <br />}
        {shown(line.text, line.start)}
      </span>
    ));
  const cells = (item) => {
    const [line] = item.lines;
    let from = 0;
    return line.text.split('\t').map((piece) => {
      const start = line.start + from;
      from += piece.length + 1;
      return { piece, start };
    });
  };

  const goTo = (n) => {
    const node = slideRefs.current.get(n);
    if (node) node.scrollIntoView?.({ block: 'start' });
    else onNavigate?.({ first: n - 1 });
  };

  const later = total - first - slides.length;
  return (
    <div style={css.root} role="region" aria-label="Presentation">
      <nav style={css.outline} aria-label="Slides">
        {outline.map((entry) => (
          <button
            key={entry.n}
            type="button"
            style={{ ...css.entry, ...(entry.n === current ? css.entryOn : null) }}
            aria-current={entry.n === current ? 'true' : undefined}
            onClick={() => goTo(entry.n)}
          >
            <span style={css.number}>{entry.n}</span>
            <span style={css.entryTitle}>{entry.title || '(no text)'}</span>
          </button>
        ))}
      </nav>
      <div style={css.slides}>
        {first > 0 && (
          <button
            type="button"
            style={css.entry}
            onClick={() => onNavigate?.({ first: Math.max(0, first - slides.length) })}
          >
            {first} earlier slides: show them
          </button>
        )}
        {slides.length === 0 && <span style={css.more}>This presentation has no text.</span>}
        {slides.map((slide) => {
          const own = slide.items.filter((i) => i.kind !== 'note');
          const spoken = slide.items.filter((i) => i.kind === 'note');
          return (
            <article
              key={slide.n}
              ref={(node) => {
                if (node) slideRefs.current.set(slide.n, node);
                else slideRefs.current.delete(slide.n);
              }}
              aria-label={`Slide ${slide.n}`}
              aria-current={slide.n === current ? 'true' : undefined}
              style={{ ...css.slide, ...(slide.n === current ? css.current : null) }}
            >
              <span style={css.label}>Slide {slide.n}</span>
              {group(own).map((g, i) => {
                if (g.type === 'list') {
                  return (
                    <ul key={i} style={css.list}>
                      {g.items.map(({ item, index }) => (
                        <li key={index} style={{ ...css.text, marginLeft: item.level * 20 }}>
                          {lines(item)}
                        </li>
                      ))}
                    </ul>
                  );
                }
                if (g.type === 'table') {
                  return (
                    <table key={i} style={css.table}>
                      <tbody>
                        {g.items.map(({ item, index }) => (
                          <tr key={index}>
                            {cells(item).map((c, j) => (
                              <td key={j} style={css.cell}>
                                {shown(c.piece, c.start)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  );
                }
                const { item } = g.items[0];
                if (g.type === 'title') {
                  return (
                    <div key={i} role="heading" aria-level={2} style={css.title}>
                      {lines(item)}
                    </div>
                  );
                }
                return (
                  <p key={i} style={g.type === 'subtitle' ? css.subtitle : css.text}>
                    {lines(item)}
                  </p>
                );
              })}
              {spoken.length > 0 && (
                <div style={css.notes} aria-label="Speaker notes">
                  <span style={css.label}>Notes</span>
                  {spoken.map((item, i) => (
                    <p key={i} style={css.text}>
                      {lines(item)}
                    </p>
                  ))}
                </div>
              )}
            </article>
          );
        })}
        {later > 0 && (
          <button
            type="button"
            style={css.entry}
            onClick={() => onNavigate?.({ first: first + slides.length })}
          >
            {later} later slides: show them
          </button>
        )}
        {notes.length > 0 && (
          <div style={css.other} aria-label="Other text">
            {notes.map((n) => (
              <p key={n.start} style={css.text}>
                {shown(n.text, n.start)}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
