import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { TextViewer } from '@vethuq/text-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A text or Markdown file of the results, shown beside them: the text as it was indexed (so the
 * match's line and column fit), a window of lines at a time, scrolled to the match and marking it.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function TextPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const { document_id: documentId, page_number: page } = match;
  const [opened, setOpened] = useState({ key: null, total: 0, error: null });
  const key = `${documentId}:${page}`;

  // The first window says how many lines there are.
  useEffect(() => {
    const controller = new AbortController();
    api.files
      .textWindow({ document_id: documentId, page, start: 0, count: 1 }, controller.signal)
      .then(
        (reply) => setOpened({ key, total: reply.total, error: null }),
        (error) => error?.name !== 'AbortError' && setOpened({ key, total: 0, error }),
      );
    return () => controller.abort();
  }, [documentId, page, key]);

  const loadLines = useCallback(
    (start, count) =>
      api.files.textWindow({ document_id: documentId, page, start, count }).then((r) => r.lines),
    [documentId, page],
  );
  const target = useMemo(
    () =>
      match.line
        ? { line: match.line, column: match.column ?? null, length: match.matched.length }
        : undefined,
    [match.line, match.column, match.matched],
  );
  const ready = opened.key === key;

  return (
    <PreviewFrame
      label="Text preview"
      match={match}
      index={index}
      count={matches.length}
      place={match.line ? `line ${match.line}` : 'page 1'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {ready && opened.error && (
          <MessageBar intent="error">
            <MessageBarBody>The text could not be shown: {opened.error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!ready && <Spinner className={styles.centered} size="small" label="Opening" />}
        {ready && !opened.error && (
          <div className={styles.viewer}>
            <TextViewer
              total={opened.total}
              loadLines={loadLines}
              target={target}
              label="Text of the file"
            />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
