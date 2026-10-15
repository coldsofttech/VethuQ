import {
  Badge,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  scroll: {
    flexGrow: 1,
    minHeight: 0,
    overflowY: 'auto',
    padding: tokens.spacingHorizontalM,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
  },
  head: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalS,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  title: { fontSize: tokens.fontSizeBase500, fontWeight: tokens.fontWeightSemibold },
  facts: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS },
  entry: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
    padding: tokens.spacingHorizontalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  current: { borderColor: tokens.colorBrandStroke1 },
  entryTitle: { fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  meta: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  text: { overflowWrap: 'anywhere' },
  link: { overflowWrap: 'anywhere', fontSize: tokens.fontSizeBase200 },
  mark: {
    backgroundColor: tokens.colorPaletteYellowBackground3,
    color: tokens.colorNeutralForeground1,
  },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

const LABELS = {
  author: 'Author: ',
  published: 'Published: ',
  categories: 'Categories: ',
  link: 'Link: ',
};

/** Only a web address is made a link (a feed can say anything). */
const isWeb = (value) => /^https?:\/\//i.test(value);

/**
 * A feed of the results beside them as a reader would show it: the feed's title and facts, then each
 * entry with its title, author, date, categories, link and text (as plain text). The entry the match
 * is in is outlined and scrolled to, and the match marked. Read from disk by the server, which lays
 * the feed out in the lines the index kept so the match can be found.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function FeedPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const path = match.file_path;
  const [feed, setFeed] = useState({ key: null, data: null, error: null });
  const key = `${path}:${match.start}`;
  const marked = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    api.files.rss({ path, at: match.start }, controller.signal).then(
      (data) => setFeed({ key, data, error: null }),
      (error) => error?.name !== 'AbortError' && setFeed({ key, data: null, error }),
    );
    return () => controller.abort();
  }, [path, match.start, key]);

  const data = feed.key === key ? feed.data : null;
  const error = feed.key === key ? feed.error : null;

  /** A line's text split around the match, with the label taken off. */
  const pieces = (line) => {
    const label = LABELS[line.kind] ?? '';
    const shown = line.text.slice(label.length);
    const from = line.start + label.length;
    const lo = Math.max(match.start, from) - from;
    const hi = Math.min(match.end, from + shown.length) - from;
    if (hi <= lo || match.end <= from || match.start >= from + shown.length) {
      return { shown, before: shown, hit: null, after: '' };
    }
    return { shown, before: shown.slice(0, lo), hit: shown.slice(lo, hi), after: shown.slice(hi) };
  };

  const render = (line, i) => {
    const { before, hit, after } = pieces(line);
    const content = (
      <>
        {before}
        {hit !== null && (
          <mark className={styles.mark} ref={marked}>
            {hit}
          </mark>
        )}
        {after}
      </>
    );
    if (line.kind === 'link' && isWeb(line.text.slice(LABELS.link.length))) {
      return (
        <a
          key={i}
          className={styles.link}
          href={line.text.slice(LABELS.link.length)}
          target="_blank"
          rel="noreferrer noopener"
        >
          {content}
        </a>
      );
    }
    if (line.kind === 'title')
      return (
        <Text key={i} className={styles.entryTitle}>
          {content}
        </Text>
      );
    if (['author', 'published', 'categories'].includes(line.kind)) {
      return (
        <Text key={i} className={styles.meta}>
          {LABELS[line.kind]}
          {content}
        </Text>
      );
    }
    return (
      <Text key={i} className={styles.text}>
        {content}
      </Text>
    );
  };

  const inEntry = (entry) =>
    entry.lines.some((l) => match.start < l.start + l.text.length && match.end > l.start);
  const where = useMemo(() => {
    if (!data) return null;
    const at = data.entries.findIndex(inEntry);
    return at < 0 ? null : data.first + at + 1;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, match.start, match.end]);

  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: 'center' });
  }, [data, match.start]);

  return (
    <PreviewFrame
      label="Feed preview"
      match={match}
      index={index}
      count={matches.length}
      place={where ? `entry ${where} of ${data.total}` : 'feed'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {error && (
          <MessageBar intent="error">
            <MessageBarBody>The feed could not be shown: {error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!data && !error && <Spinner className={styles.centered} size="small" label="Opening" />}
        {data && (
          <div className={styles.scroll}>
            {!data.well_formed && (
              <MessageBar intent="info">
                <MessageBarBody>
                  This feed is not well-formed, so only its text is shown, as it was indexed.
                </MessageBarBody>
              </MessageBar>
            )}
            {data.head.length > 0 && (
              <div className={styles.head}>
                {data.head.map((line, i) =>
                  line.kind === 'title' ? (
                    <Text key={i} className={styles.title}>
                      {render({ ...line, kind: 'plain' }, i)}
                    </Text>
                  ) : (
                    render({ ...line, kind: 'plain' }, i)
                  ),
                )}
                <div className={styles.facts}>
                  <Badge appearance="tint">{data.format}</Badge>
                  {data.language && <Badge appearance="tint">{data.language}</Badge>}
                  {data.updated && <Badge appearance="tint">{data.updated}</Badge>}
                  <Badge appearance="tint">
                    {data.total} {data.total === 1 ? 'entry' : 'entries'}
                  </Badge>
                </div>
              </div>
            )}
            {data.first > 0 && (
              <Text className={styles.meta}>{data.first} earlier entries not shown.</Text>
            )}
            {data.entries.map((entry, i) => (
              <article
                key={data.first + i}
                className={`${styles.entry} ${inEntry(entry) ? styles.current : ''}`}
                aria-current={inEntry(entry) || undefined}
              >
                {entry.lines.map(render)}
              </article>
            ))}
            {data.first + data.entries.length < data.total && (
              <Text className={styles.meta}>
                {data.total - data.first - data.entries.length} later entries not shown.
              </Text>
            )}
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
