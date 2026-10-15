import { useEffect, useMemo, useRef } from 'react';

const css = {
  root: {
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    fontSize: 14,
    background: 'var(--colorNeutralBackground2, #fafafa)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  notice: {
    padding: '6px 10px',
    borderRadius: 4,
    fontSize: 13,
    background: 'var(--colorNeutralBackground3, #f5f5f5)',
    border: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
  },
  head: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    paddingBottom: 8,
    borderBottom: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
  },
  title: { fontSize: 20, fontWeight: 600 },
  facts: { display: 'flex', flexWrap: 'wrap', gap: 4 },
  fact: {
    padding: '1px 8px',
    borderRadius: 10,
    fontSize: 12,
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    color: 'var(--colorNeutralForeground2, #424242)',
  },
  entry: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: 12,
    borderRadius: 6,
    border: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  current: { borderColor: 'var(--colorBrandStroke1, #0f6cbd)' },
  entryTitle: { fontSize: 16, fontWeight: 600 },
  meta: { fontSize: 12, color: 'var(--colorNeutralForeground3, #707070)' },
  text: { overflowWrap: 'anywhere' },
  link: { fontSize: 12, overflowWrap: 'anywhere' },
  more: { fontSize: 12, color: 'var(--colorNeutralForeground3, #707070)' },
  mark: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
    color: 'inherit',
  },
};

/** The label a line carries in the text the index kept, which is not shown in the line itself. */
const LABELS = {
  author: 'Author: ',
  published: 'Published: ',
  categories: 'Categories: ',
  link: 'Link: ',
};

/** Only a web address is made a link (a feed can say anything). */
const isWeb = (value) => /^https?:\/\//i.test(value);

/**
 * A line's text split around the match: what is shown (its label taken off) before the match, the
 * match, and after it. `hit` is null when the match is not in this line.
 */
function pieces(line, match) {
  const label = LABELS[line.kind] ?? '';
  const shown = line.text.slice(label.length);
  const from = line.start + label.length;
  const lo = Math.max(match.start, from) - from;
  const hi = Math.min(match.end, from + shown.length) - from;
  if (hi <= lo || match.end <= from || match.start >= from + shown.length) {
    return { before: shown, hit: null, after: '' };
  }
  return { before: shown.slice(0, lo), hit: shown.slice(lo, hi), after: shown.slice(hi) };
}

/** Whether the match falls in a line (or, for an entry, any of its lines). */
const inLine = (line, match) =>
  match.start < line.start + line.text.length && match.end > line.start;

/**
 * A read-only reader for an RSS or Atom feed, as laid out by whoever supplies it: the feed's title
 * and facts, then each entry as a card with its title, author, date, categories, link and text.
 * Each line carries its `kind` and its `start`, its offset in the text the feed was indexed as (the
 * lines joined by a newline), which is how a match in that text is found and marked. The entry the
 * match is in is outlined and scrolled to.
 *
 * @param {object} props
 * @param {object} props.feed
 * @param {string} [props.feed.format] `rss`, `rdf` or `atom`.
 * @param {string | null} [props.feed.language]
 * @param {string | null} [props.feed.updated]
 * @param {boolean} [props.feed.well_formed] False: only the text could be read, and a note says so.
 * @param {Array<{kind: string, text: string, start: number}>} props.feed.head The feed's own lines.
 * @param {Array<{lines: Array<{kind: string, text: string, start: number}>}>} props.feed.entries
 *   The entries shown (a window of the feed).
 * @param {number} props.feed.first How many entries come before the first one shown.
 * @param {number} props.feed.total How many entries the feed has.
 * @param {{start: number, end: number} | null} [props.match] The match, as offsets in the indexed text.
 * @param {(entry: number | null) => void} [props.onLocated] Called with the number (from 1) of the
 *   entry the match is in, or null if it is in none of those shown.
 */
export function FeedViewer({ feed, match = null, onLocated }) {
  const marked = useRef(null);
  const target = match ?? { start: -1, end: -1 };

  const current = useMemo(() => {
    const at = feed.entries.findIndex((entry) => entry.lines.some((l) => inLine(l, target)));
    return at < 0 ? null : at;
  }, [feed, target.start, target.end]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    onLocated?.(current === null ? null : feed.first + current + 1);
  }, [current, feed.first, onLocated]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center' });
  }, [feed, target.start]);

  const render = (line, key, kind = line.kind) => {
    const { before, hit, after } = pieces(line, target);
    const content = (
      <>
        {before}
        {hit !== null && (
          <mark style={css.mark} ref={marked}>
            {hit}
          </mark>
        )}
        {after}
      </>
    );
    const address = line.text.slice(LABELS.link.length);
    if (kind === 'link' && isWeb(address)) {
      return (
        <a key={key} style={css.link} href={address} target="_blank" rel="noreferrer noopener">
          {content}
        </a>
      );
    }
    if (kind === 'title') {
      return (
        <span key={key} style={css.entryTitle}>
          {content}
        </span>
      );
    }
    if (kind in LABELS) {
      return (
        <span key={key} style={css.meta}>
          {LABELS[kind]}
          {content}
        </span>
      );
    }
    return (
      <span key={key} style={css.text}>
        {content}
      </span>
    );
  };

  const later = feed.total - feed.first - feed.entries.length;
  return (
    <div style={css.root} role="region" aria-label="Feed">
      {feed.well_formed === false && (
        <div style={css.notice} role="note">
          This feed is not well-formed, so only its text is shown, as it was indexed.
        </div>
      )}
      {feed.head.length > 0 && (
        <div style={css.head}>
          {feed.head.map((line, i) =>
            line.kind === 'title' ? (
              <span key={i} style={css.title}>
                {render(line, i, 'plain')}
              </span>
            ) : (
              render(line, i, 'plain')
            ),
          )}
          <div style={css.facts}>
            {feed.format && <span style={css.fact}>{feed.format}</span>}
            {feed.language && <span style={css.fact}>{feed.language}</span>}
            {feed.updated && <span style={css.fact}>{feed.updated}</span>}
            <span style={css.fact}>
              {feed.total} {feed.total === 1 ? 'entry' : 'entries'}
            </span>
          </div>
        </div>
      )}
      {feed.first > 0 && <span style={css.more}>{feed.first} earlier entries not shown.</span>}
      {feed.entries.map((entry, i) => (
        <article
          key={feed.first + i}
          style={{ ...css.entry, ...(i === current ? css.current : null) }}
          aria-current={i === current ? 'true' : undefined}
        >
          {entry.lines.map((line, j) => render(line, j))}
        </article>
      ))}
      {later > 0 && <span style={css.more}>{later} later entries not shown.</span>}
    </div>
  );
}
