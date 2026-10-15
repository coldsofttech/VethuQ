import { useEffect, useRef } from 'react';

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
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    padding: 12,
    borderRadius: 6,
    border: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
    background: 'var(--colorNeutralBackground1, #fff)',
  },
  subject: { fontSize: 18, fontWeight: 600, overflowWrap: 'anywhere' },
  row: { display: 'flex', gap: 8, overflowWrap: 'anywhere' },
  label: {
    flexShrink: 0,
    width: 72,
    fontSize: 12,
    color: 'var(--colorNeutralForeground3, #707070)',
  },
  attachments: { display: 'flex', flexWrap: 'wrap', gap: 4 },
  attachment: {
    padding: '1px 8px',
    borderRadius: 10,
    fontSize: 12,
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    color: 'var(--colorNeutralForeground2, #424242)',
  },
  body: {
    margin: 0,
    fontFamily: 'inherit',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
  empty: { fontSize: 12, color: 'var(--colorNeutralForeground3, #707070)' },
  mark: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
    color: 'inherit',
  },
};

/** The label a header line carries in the text the index kept, and the one it is shown with. */
const LABELS = {
  from: ['From: ', 'From'],
  to: ['To: ', 'To'],
  cc: ['Cc: ', 'Cc'],
  bcc: ['Bcc: ', 'Bcc'],
  reply_to: ['Reply-To: ', 'Reply-To'],
  subject: ['Subject: ', 'Subject'],
  date: ['Date: ', 'Date'],
  message_id: ['Message-ID: ', 'Message-ID'],
};

/** A size in bytes in words. */
function size(bytes) {
  if (typeof bytes !== 'number' || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A line's shown text (its label taken off) split around the match. */
function pieces(text, from, match) {
  const lo = Math.max(match.start, from) - from;
  const hi = Math.min(match.end, from + text.length) - from;
  if (hi <= lo) return { before: text, hit: null, after: '' };
  return { before: text.slice(0, lo), hit: text.slice(lo, hi), after: text.slice(hi) };
}

/**
 * A read-only reader for an email message: a card with its headers, the attachments it carries
 * (their names, types and sizes), then the body as text. Each line carries its `start`, its offset
 * in the text the message was indexed as (the header lines joined by a newline, a blank line, the
 * body), which is how a match in that text is found and marked.
 *
 * @param {object} props
 * @param {object} props.message
 * @param {Array<{kind: string, text: string, start: number}>} props.message.head The header lines,
 *   `kind` being `from`, `to`, `cc`, `bcc`, `reply_to`, `subject`, `date` or `message_id`.
 * @param {Array<{text: string, start: number}>} props.message.body The body, a line each.
 * @param {Array<{name: string, type: string | null, size: number | null}>} [props.message.attachments]
 * @param {{start: number, end: number} | null} [props.match] The match, as offsets in the indexed text.
 * @param {(place: 'headers' | 'body' | null) => void} [props.onLocated] Called with where the match
 *   is, or null if it is in neither.
 */
export function EmailViewer({ message, match = null, onLocated }) {
  const marked = useRef(null);
  const target = match ?? { start: -1, end: -1 };
  const attachments = message.attachments ?? [];

  const hits = (line) => target.start < line.start + line.text.length && target.end > line.start;
  const place = message.head.some(hits) ? 'headers' : message.body.some(hits) ? 'body' : null;

  useEffect(() => {
    onLocated?.(place);
  }, [place, onLocated]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center' });
  }, [message, target.start]);

  const mark = (text, from) => {
    const { before, hit, after } = pieces(text, from, target);
    return (
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
  };

  const [subject, rest] = [
    message.head.find((line) => line.kind === 'subject'),
    message.head.filter((line) => line.kind !== 'subject'),
  ];
  const row = (line) => {
    const [prefix, name] = LABELS[line.kind] ?? ['', line.kind];
    return (
      <div key={line.kind} style={css.row}>
        <span style={css.label}>{name}</span>
        <span>{mark(line.text.slice(prefix.length), line.start + prefix.length)}</span>
      </div>
    );
  };

  return (
    <div style={css.root} role="region" aria-label="Email">
      <div style={css.card} aria-current={place === 'headers' ? 'true' : undefined}>
        {subject && (
          <span style={css.subject}>
            {mark(
              subject.text.slice(LABELS.subject[0].length),
              subject.start + LABELS.subject[0].length,
            )}
          </span>
        )}
        {rest.map(row)}
        {message.head.length === 0 && <span style={css.empty}>This message has no headers.</span>}
      </div>
      {attachments.length > 0 && (
        <div style={css.attachments} role="list" aria-label="Attachments">
          {attachments.map((file, i) => (
            <span key={i} style={css.attachment} role="listitem" title={file.type ?? undefined}>
              {file.name}
              {size(file.size) && ` (${size(file.size)})`}
            </span>
          ))}
        </div>
      )}
      <div style={css.card} aria-current={place === 'body' ? 'true' : undefined}>
        {message.body.length === 0 ? (
          <span style={css.empty}>This message has no text.</span>
        ) : (
          <pre style={css.body}>
            {message.body.map((line, i) => (
              <span key={i}>
                {i > 0 && '\n'}
                {mark(line.text, line.start)}
              </span>
            ))}
          </pre>
        )}
      </div>
    </div>
  );
}
