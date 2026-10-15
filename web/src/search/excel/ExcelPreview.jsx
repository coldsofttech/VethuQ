import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ExcelViewer } from '@vethuq/excel-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A spreadsheet of the results beside them as a spreadsheet program would show it (the Excel
 * viewer): tabs for its sheets and a grid of cells, a window of rows at a time. The cell the match
 * is in is outlined and scrolled to, and the match marked. The server lays out the text the index
 * kept (so the match can be found) over the cells the file holds.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function ExcelPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const { document_id: documentId, page_number: page } = match;
  const key = `${documentId}:${page}:${match.start}`;
  // Which sheet and rows to show once the person has moved off the match's own.
  const [moved, setMoved] = useState({ key: null, sheet: undefined, first: undefined });
  const [book, setBook] = useState({ key: null, data: null, error: null });
  const [located, setLocated] = useState({ key: null, place: null });
  const asked = moved.key === key ? moved : { sheet: undefined, first: undefined };
  const request = `${key}:${asked.sheet}:${asked.first}`;

  useEffect(() => {
    const controller = new AbortController();
    const params = { document_id: documentId, page, at: match.start };
    if (asked.sheet !== undefined) params.sheet = asked.sheet;
    if (asked.first != null) params.first = asked.first;
    api.files.excel(params, controller.signal).then(
      (data) => setBook({ key: request, data, error: null }),
      (error) => error?.name !== 'AbortError' && setBook({ key: request, data: null, error }),
    );
    return () => controller.abort();
  }, [documentId, page, match.start, asked.sheet, asked.first, request]);

  const data = book.key === request ? book.data : null;
  const error = book.key === request ? book.error : null;
  const words = useMemo(() => ({ start: match.start, end: match.end }), [match.start, match.end]);
  const onLocated = useMemo(() => (place) => setLocated({ key: request, place }), [request]);
  const onNavigate = useCallback(
    ({ sheet, first }) => setMoved({ key, sheet, first: first ?? undefined }),
    [key],
  );
  const place = located.key === request ? located.place : null;

  return (
    <PreviewFrame
      label="Excel preview"
      match={match}
      index={index}
      count={matches.length}
      place={place ?? 'workbook'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {error && (
          <MessageBar intent="error">
            <MessageBarBody>The workbook could not be shown: {error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!data && !error && <Spinner className={styles.centered} size="small" label="Opening" />}
        {data && (
          <div className={styles.viewer}>
            <ExcelViewer
              workbook={data}
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
