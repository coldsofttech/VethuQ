import {
  MessageBar,
  MessageBarBody,
  Spinner,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { TextViewer, locateWords, vscodeDark, vscodeLight } from '@vethuq/text-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { useTheme } from '../../theme/ThemeProvider.jsx';
import { PreviewFrame } from '../PreviewFrame.jsx';
import { LANGUAGES } from './languages.js';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

// A file bigger than this is not laid out (that would be a lot of text to make): its source is shown.
const FORMAT_LIMIT = 20 * 1024 * 1024;
// A line longer than this is not drawn in full (nor coloured): a minified file is one such line.
const LONG_LINE = 20000;
// A file with a line this long is shown laid out (when its language can be) until told otherwise.
const MINIFIED = 2000;

/**
 * A CSS, JavaScript, JSON, YAML or XML file of the results beside them, as Visual Studio Code would
 * show it: line numbers and the colours of its Dark+ or Light+ theme (following the app's), read from
 * disk (the index keeps these in another shape, so its lines are not the file's). A minified file
 * opens laid out, and the Source / Formatted switch (where the language has a layout) changes it.
 * The match is found in the text shown by its words, and under its key for a file indexed as
 * `key: value` lines, and marked on its line.
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

  useEffect(() => {
    const controller = new AbortController();
    api.files.source(match.file_type, { path }, controller.signal).then(
      (reply) => setFile({ path, text: reply.text, longest: reply.longest_line, error: null }),
      (error) => error?.name !== 'AbortError' && setFile({ path, text: null, longest: 0, error }),
    );
    return () => controller.abort();
  }, [path, match.file_type]);

  const text = file.path === path ? file.text : null;
  const tooBig = text !== null && text.length > FORMAT_LIMIT;
  const canFormat = Boolean(language.format) && !tooBig;
  const mode = !canFormat
    ? 'source'
    : (choice ?? (file.longest > MINIFIED ? 'formatted' : 'source'));
  const shown = useMemo(
    () => (text === null ? null : mode === 'formatted' ? language.format(text) : text),
    [text, mode, language],
  );
  const lines = useMemo(() => (shown === null ? [] : shown.split('\n')), [shown]);
  const highlighter = useMemo(() => new language.Highlighter(lines), [lines, language]);
  const colour = useCallback(
    (_, line) => (lines[line].length > LONG_LINE ? null : highlighter.segments(line)),
    [lines, highlighter],
  );
  const loadLines = useCallback(
    (start, count) =>
      Promise.resolve(
        lines
          .slice(start, start + count)
          .map((l) => (l.length > LONG_LINE ? `${l.slice(0, LONG_LINE)}…` : l)),
      ),
    [lines],
  );

  const where = useMemo(
    () =>
      shown === null
        ? null
        : locateWords(shown, {
            before: match.before,
            matched: match.matched,
            after: match.after,
            hint: language.hint(match.before) ?? undefined,
          }),
    [shown, match.before, match.matched, match.after, language],
  );
  const target = useMemo(
    () =>
      where
        ? { line: where.line, column: where.column, length: where.end - where.offset }
        : undefined,
    [where],
  );

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
            <TextViewer
              key={`${path}:${mode}`}
              total={lines.length}
              loadLines={loadLines}
              tokens={colour}
              theme={isDark ? vscodeDark : vscodeLight}
              target={target}
              label={`${language.label} source`}
            />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
