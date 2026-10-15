import {
  MessageBar,
  MessageBarBody,
  Spinner,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { CodeViewer, LANGUAGES, codeMode } from '@vethuq/code-viewer';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { useTheme } from '../../theme/ThemeProvider.jsx';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

/**
 * A CSS, JavaScript, JSON, NDJSON, YAML, TOML, INI, SQL, reStructuredText, log or XML file of the results beside them, read from disk
 * (the index keeps these in another shape, so its lines are not the file's) and shown by the code
 * viewer: line numbers and the colours of VS Code's Dark+ or Light+ theme (following the app's). A
 * minified file opens laid out, and the Source / Formatted switch (where the language has a layout)
 * changes it. The match is marked on its line.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function CodePreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const { isDark } = useTheme();
  const match = matches[index];
  const path = match.file_path;
  const language = LANGUAGES[match.file_type];
  const [file, setFile] = useState({ path: null, text: null, longest: 0, error: null });
  const [choice, setChoice] = useState(null);
  const [located, setLocated] = useState({ key: null, where: null });

  useEffect(() => {
    const controller = new AbortController();
    api.files.source(match.file_type, { path }, controller.signal).then(
      (reply) => setFile({ path, text: reply.text, longest: reply.longest_line, error: null }),
      (error) => error?.name !== 'AbortError' && setFile({ path, text: null, longest: 0, error }),
    );
    return () => controller.abort();
  }, [path, match.file_type]);

  const text = file.path === path ? file.text : null;
  const { mode, tooBig } = codeMode(match.file_type, text, file.longest, choice);
  const words = useMemo(
    () => ({ before: match.before, matched: match.matched, after: match.after }),
    [match.before, match.matched, match.after],
  );
  // Where the viewer found the match in the text it shows (null: it is not there).
  const viewKey = `${path}:${mode}:${match.before}:${match.matched}:${match.after}`;
  const where = located.key === viewKey ? located.where : undefined;
  const onLocated = useMemo(() => (found) => setLocated({ key: viewKey, where: found }), [viewKey]);

  return (
    <PreviewFrame
      label="Code preview"
      match={match}
      index={index}
      count={matches.length}
      place={where ? `line ${where.line}` : language.label}
      onIndex={onIndex}
      onClose={onClose}
      tools={
        language.format ? (
          <TabList
            size="small"
            selectedValue={mode}
            onTabSelect={(_, data) => setChoice(data.value)}
            aria-label="View"
          >
            <Tab value="source">Source</Tab>
            <Tab
              value="formatted"
              disabled={tooBig}
              title={tooBig ? 'Too large to lay out' : undefined}
            >
              Formatted
            </Tab>
          </TabList>
        ) : undefined
      }
    >
      <div className={styles.body}>
        {file.path === path && file.error && (
          <MessageBar intent="error">
            <MessageBarBody>The file could not be shown: {file.error.message}</MessageBarBody>
          </MessageBar>
        )}
        {text !== null && where === null && (
          <MessageBar intent="warning">
            <MessageBarBody>
              The words are not in the file as it is now (it may have changed since it was read, or
              they came from a picture).
            </MessageBarBody>
          </MessageBar>
        )}
        {text === null && !file.error && (
          <Spinner className={styles.centered} size="small" label="Opening" />
        )}
        {text !== null && (
          <div className={styles.viewer}>
            <CodeViewer
              key={path}
              text={text}
              language={match.file_type}
              mode={mode}
              match={words}
              dark={isDark}
              onLocated={onLocated}
            />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
