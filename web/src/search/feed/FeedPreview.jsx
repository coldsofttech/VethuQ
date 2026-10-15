import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { FeedViewer } from '@vethuq/feed-viewer';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A feed of the results beside them as a reader would show it (the feed viewer): the feed's title and
 * facts, then each entry with its title, author, date, categories, link and text. The entry the
 * match is in is outlined and scrolled to, and the match marked. Read from disk by the server, which
 * lays the feed out in the lines the index kept so the match can be found.
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
  const [located, setLocated] = useState({ key: null, entry: null });
  const key = `${path}:${match.start}`;

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
  const words = useMemo(() => ({ start: match.start, end: match.end }), [match.start, match.end]);
  const onLocated = useMemo(() => (entry) => setLocated({ key, entry }), [key]);
  const entry = located.key === key ? located.entry : null;

  return (
    <PreviewFrame
      label="Feed preview"
      match={match}
      index={index}
      count={matches.length}
      place={entry && data ? `entry ${entry} of ${data.total}` : 'feed'}
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
          <div className={styles.viewer}>
            <FeedViewer feed={data} match={words} onLocated={onLocated} />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
