import {
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { EmailViewer } from '@vethuq/email-viewer';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * An email message of the results beside them as a mail program would show it (the email viewer):
 * its headers, attachments and body. The match is marked and scrolled to. Read from disk by the
 * server, which lays the message out in the lines the index kept so the match can be found.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function EmailPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const path = match.file_path;
  const [mail, setMail] = useState({ key: null, data: null, error: null });
  const [located, setLocated] = useState({ key: null, place: null });
  const key = `${path}:${match.start}`;

  useEffect(() => {
    const controller = new AbortController();
    api.files.email({ path, kind: match.file_type }, controller.signal).then(
      (data) => setMail({ key, data, error: null }),
      (error) => error?.name !== 'AbortError' && setMail({ key, data: null, error }),
    );
    return () => controller.abort();
  }, [path, match.start, match.file_type, key]);

  const data = mail.key === key ? mail.data : null;
  const error = mail.key === key ? mail.error : null;
  const words = useMemo(() => ({ start: match.start, end: match.end }), [match.start, match.end]);
  const onLocated = useMemo(() => (place) => setLocated({ key, place }), [key]);
  const place = located.key === key ? located.place : null;

  return (
    <PreviewFrame
      label="Email preview"
      match={match}
      index={index}
      count={matches.length}
      place={place ?? 'message'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        {error && (
          <MessageBar intent="error">
            <MessageBarBody>The message could not be shown: {error.message}</MessageBarBody>
          </MessageBar>
        )}
        {!data && !error && <Spinner className={styles.centered} size="small" label="Opening" />}
        {data && (
          <div className={styles.viewer}>
            <EmailViewer message={data} match={words} onLocated={onLocated} />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
