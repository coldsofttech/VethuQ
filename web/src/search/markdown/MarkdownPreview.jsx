import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  Spinner,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { MarkdownViewer, locateInSource } from '@vethuq/markdown-viewer';
import { TextViewer } from '@vethuq/text-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

const MODE_KEY = 'vethuq.markdown-view';
const readMode = () => {
  try {
    return localStorage.getItem(MODE_KEY) === 'source' ? 'source' : 'rendered';
  } catch {
    return 'rendered';
  }
};

/**
 * A Markdown file of the results beside them: rendered (the default) or as its source, read from
 * disk. The match is found in the file's text, then marked in the block that holds it (rendered) or
 * on its line (source). A match in markup that does not show, such as a link's address, is said to
 * be hidden, with a way to see the source.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function MarkdownPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const path = match.file_path;
  const [file, setFile] = useState({ path: null, text: null, error: null });
  const [mode, setMode] = useState(readMode);
  const [marked, setMarked] = useState({ key: null, found: null });

  useEffect(() => {
    const controller = new AbortController();
    api.files.markdown({ path }, controller.signal).then(
      (reply) => setFile({ path, text: reply.text, error: null }),
      (error) => error?.name !== 'AbortError' && setFile({ path, text: null, error }),
    );
    return () => controller.abort();
  }, [path]);

  const text = file.path === path ? file.text : null;
  const where = useMemo(
    () =>
      text === null
        ? null
        : locateInSource(text, {
            before: match.before,
            matched: match.matched,
            after: match.after,
          }),
    [text, match.before, match.matched, match.after],
  );
  const lines = useMemo(() => (text === null ? [] : text.split('\n')), [text]);
  const loadLines = useCallback(
    (start, count) => Promise.resolve(lines.slice(start, start + count)),
    [lines],
  );

  const key = `${path}:${match.start}:${match.page_number}`;
  const rendered = useMemo(
    () =>
      where
        ? { line: where.line, before: match.before, matched: match.matched, after: match.after }
        : undefined,
    [where, match.before, match.matched, match.after],
  );
  const asSource = useMemo(
    () =>
      where
        ? { line: where.line, column: where.column, length: where.end - where.offset }
        : undefined,
    [where],
  );
  const onMarked = useCallback((found) => setMarked({ key, found }), [key]);
  const chooseMode = (next) => {
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      // Not remembered; it still changes.
    }
  };

  const hidden = mode === 'rendered' && marked.key === key && marked.found === false;
  const unfound = text !== null && where === null;

  return (
    <PreviewFrame
      label="Markdown preview"
      match={match}
      index={index}
      count={matches.length}
      place={where ? `line ${where.line}` : 'Markdown'}
      onIndex={onIndex}
      onClose={onClose}
      tools={
        <TabList
          size="small"
          selectedValue={mode}
          onTabSelect={(_, data) => chooseMode(data.value)}
          aria-label="View"
        >
          <Tab value="rendered">Rendered</Tab>
          <Tab value="source">Source</Tab>
        </TabList>
      }
    >
      <div className={styles.body}>
        {file.path === path && file.error && (
          <MessageBar intent="error">
            <MessageBarBody>The file could not be shown: {file.error.message}</MessageBarBody>
          </MessageBar>
        )}
        {unfound && (
          <MessageBar intent="warning">
            <MessageBarBody>
              The words are not in the file as it is now (it may have changed since it was read, or
              they came from a picture).
            </MessageBarBody>
          </MessageBar>
        )}
        {hidden && (
          <MessageBar intent="info">
            <MessageBarBody>
              This match is not visible in the rendered view (it may be in a link address or other
              markup).
            </MessageBarBody>
            <MessageBarActions>
              <Button size="small" onClick={() => chooseMode('source')}>
                Show source
              </Button>
            </MessageBarActions>
          </MessageBar>
        )}
        {text === null && !file.error && (
          <Spinner className={styles.centered} size="small" label="Opening" />
        )}
        {text !== null && (
          <div className={styles.viewer}>
            {mode === 'rendered' ? (
              <MarkdownViewer
                key={path}
                text={text}
                target={rendered}
                onMarked={onMarked}
                label="Rendered Markdown"
              />
            ) : (
              <TextViewer
                key={path}
                total={lines.length}
                loadLines={loadLines}
                target={asSource}
                label="Markdown source"
              />
            )}
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
