import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { WordViewer } from '@vethuq/word-viewer';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A Word, RTF or OpenDocument text document of the results beside them as a page (the word viewer):
 * its paragraphs, with headings, lists and tables where the file says so. The match is marked and
 * scrolled to. The server lays out the text the index kept (so the match can be found) and puts the
 * file's structure over it.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function WordPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const { document_id: documentId, page_number: page } = match;
  const [doc, setDoc] = useState({ key: null, data: null, error: null });
  const [located, setLocated] = useState({ key: null, line: null });
  const key = `${documentId}:${page}:${match.start}`;

  useEffect(() => {
    const controller = new AbortController();
    api.files.word({ document_id: documentId, page, at: match.start }, controller.signal).then(
      (data) => setDoc({ key, data, error: null }),
      (error) => error?.name !== 'AbortError' && setDoc({ key, data: null, error }),
    );
    return () => controller.abort();
  }, [documentId, page, match.start, key]);

  const data = doc.key === key ? doc.data : null;
  const error = doc.key === key ? doc.error : null;
  const words = useMemo(() => ({ start: match.start, end: match.end }), [match.start, match.end]);
  const onLocated = useMemo(() => (line) => setLocated({ key, line }), [key]);
  const line = located.key === key ? located.line : null;

  return (
    <PreviewFrame
      label="Word preview"
      match={match}
      index={index}
      count={matches.length}
      place={line && data ? `line ${line} of ${data.total}` : 'document'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {error && (
          <MessageBar intent="error">
            <MessageBarBody>The document could not be shown: {error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!data && !error && <Spinner className={styles.centered} size="small" label="Opening" />}
        {data && (
          <div className={styles.viewer}>
            <WordViewer document={data} match={words} onLocated={onLocated} />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
