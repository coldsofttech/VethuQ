import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { PowerPointViewer } from '@vethuq/powerpoint-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A PowerPoint or OpenDocument presentation of the results beside them, slide by slide (the
 * PowerPoint viewer): an outline of the slides and each slide's title, text, tables and speaker
 * notes. The slide the match is in is outlined and scrolled to, and the match marked. The server lays
 * out the text the index kept (so the match can be found) over the slides the file holds.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function PowerPointPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const { document_id: documentId, page_number: page } = match;
  const key = `${documentId}:${page}:${match.start}`;
  // Which slides to show once the person has moved off the match's own.
  const [moved, setMoved] = useState({ key: null, first: undefined });
  const [deck, setDeck] = useState({ key: null, data: null, error: null });
  const [located, setLocated] = useState({ key: null, place: null });
  const asked = moved.key === key ? moved.first : undefined;
  const request = `${key}:${asked}`;

  useEffect(() => {
    const controller = new AbortController();
    const params = { document_id: documentId, page, at: match.start };
    if (asked !== undefined) params.first = asked;
    api.files.powerpoint(params, controller.signal).then(
      (data) => setDeck({ key: request, data, error: null }),
      (error) => error?.name !== 'AbortError' && setDeck({ key: request, data: null, error }),
    );
    return () => controller.abort();
  }, [documentId, page, match.start, asked, request]);

  const data = deck.key === request ? deck.data : null;
  const error = deck.key === request ? deck.error : null;
  const words = useMemo(() => ({ start: match.start, end: match.end }), [match.start, match.end]);
  const onLocated = useMemo(() => (place) => setLocated({ key: request, place }), [request]);
  const onNavigate = useCallback(({ first }) => setMoved({ key, first }), [key]);
  const place = located.key === request ? located.place : null;

  return (
    <PreviewFrame
      label="PowerPoint preview"
      match={match}
      index={index}
      count={matches.length}
      place={place ?? 'presentation'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {error && (
          <MessageBar intent="error">
            <MessageBarBody>The presentation could not be shown: {error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!data && !error && <Spinner className={styles.centered} size="small" label="Opening" />}
        {data && (
          <div className={styles.viewer}>
            <PowerPointViewer
              deck={data}
              match={words}
              onNavigate={onNavigate}
              onLocated={onLocated}
            />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
