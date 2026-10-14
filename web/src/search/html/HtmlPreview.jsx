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
import { HtmlViewer } from '@vethuq/html-viewer';
import {
  HtmlHighlighter,
  TextViewer,
  formatHtml,
  locateInHtml,
  vscodeDark,
  vscodeLight,
} from '@vethuq/text-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { useTheme } from '../../theme/ThemeProvider.jsx';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

// A page bigger than this is not rendered (it is one document in a frame, not windowed): its source is shown.
const RENDER_LIMIT = 5 * 1024 * 1024;
// A web archive's page carries its pictures in it (the server puts in up to 24 MB of them), so its
// limit is larger.
const ARCHIVE_RENDER_LIMIT = 48 * 1024 * 1024;
// A line longer than this is not drawn in full (nor coloured).
const LONG_LINE = 20000;

const MODE_KEY = 'vethuq.html-view';
const MODES = ['rendered', 'source', 'formatted'];
const readMode = () => {
  try {
    const stored = localStorage.getItem(MODE_KEY);
    return MODES.includes(stored) ? stored : 'rendered';
  } catch {
    return 'rendered';
  }
};

/**
 * A web page of the results beside them, read from disk: rendered by the browser in a sandboxed
 * frame (the default; nothing runs and nothing is fetched), or as its source in Visual Studio Code's
 * colours, as written or laid out one tag to a line. The match is found in the page's visible text,
 * then marked in the rendered page, or on its line in the source. A match in text the page does not
 * show (its title, an image's alt text) is said to be hidden, with a way to see the source.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function HtmlPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const { isDark } = useTheme();
  const match = matches[index];
  const path = match.file_path;
  const archive = match.file_type === 'mhtml';
  const [file, setFile] = useState({ path: null, text: null, rendered: null, error: null });
  const [choice, setChoice] = useState(readMode);
  const [marked, setMarked] = useState({ key: null, found: null });

  useEffect(() => {
    const controller = new AbortController();
    (archive ? api.files.mhtml : api.files.html)({ path }, controller.signal).then(
      (reply) =>
        setFile({
          path,
          text: reply.text,
          rendered: reply.rendered ?? null,
          incomplete: Boolean(reply.incomplete),
          error: null,
        }),
      (error) =>
        error?.name !== 'AbortError' && setFile({ path, text: null, rendered: null, error }),
    );
    return () => controller.abort();
  }, [path, archive]);

  const text = file.path === path ? file.text : null;
  const rendered = file.path === path ? file.rendered : null;
  const tooBig =
    text !== null && (rendered ?? text).length > (archive ? ARCHIVE_RENDER_LIMIT : RENDER_LIMIT);
  const mode = choice === 'rendered' && tooBig ? 'source' : choice;
  const choose = (next) => {
    setChoice(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      // Not remembered; it still changes.
    }
  };

  const shown = useMemo(() => {
    if (text === null || mode === 'rendered') return null;
    return mode === 'formatted' ? formatHtml(text) : text;
  }, [text, mode]);
  const lines = useMemo(() => (shown === null ? [] : shown.split('\n')), [shown]);
  const highlighter = useMemo(() => new HtmlHighlighter(lines), [lines]);
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

  const words = useMemo(
    () => ({ before: match.before, matched: match.matched, after: match.after }),
    [match.before, match.matched, match.after],
  );
  const where = useMemo(() => (shown === null ? null : locateInHtml(shown, words)), [shown, words]);
  const target = useMemo(
    () =>
      where
        ? { line: where.line, column: where.column, length: where.end - where.offset }
        : undefined,
    [where],
  );

  const key = `${path}:${match.start}:${match.page_number}`;
  const onMarked = useCallback((found) => setMarked({ key, found }), [key]);
  const hidden = mode === 'rendered' && marked.key === key && marked.found === false;
  const unfound = text !== null && mode !== 'rendered' && where === null;

  return (
    <PreviewFrame
      label="Web page preview"
      match={match}
      index={index}
      count={matches.length}
      place={
        mode !== 'rendered' && where ? `line ${where.line}` : archive ? 'web archive' : 'web page'
      }
      onIndex={onIndex}
      onClose={onClose}
      tools={
        <TabList
          size="small"
          selectedValue={mode}
          onTabSelect={(_, data) => choose(data.value)}
          aria-label="View"
        >
          <Tab
            value="rendered"
            disabled={tooBig}
            title={tooBig ? 'Too large to render' : undefined}
          >
            Rendered
          </Tab>
          <Tab value="source">Source</Tab>
          <Tab value="formatted">Formatted</Tab>
        </TabList>
      }
    >
      <div className={styles.body}>
        {file.path === path && file.error && (
          <MessageBar intent="error">
            <MessageBarBody>The page could not be shown: {file.error.message}</MessageBarBody>
          </MessageBar>
        )}
        {tooBig && (
          <MessageBar intent="info">
            <MessageBarBody>
              This page is too large to render here, so its source is shown.
            </MessageBarBody>
          </MessageBar>
        )}
        {file.path === path && file.incomplete && mode === 'rendered' && (
          <MessageBar intent="info">
            <MessageBarBody>
              This archive is large: some of its pictures and styles are left out of the page shown
              here.
            </MessageBarBody>
          </MessageBar>
        )}
        {unfound && (
          <MessageBar intent="warning">
            <MessageBarBody>
              The words are not in the page as it is now (it may have changed since it was read, or
              they came from a picture).
            </MessageBarBody>
          </MessageBar>
        )}
        {hidden && (
          <MessageBar intent="info">
            <MessageBarBody>
              This match is not visible on the rendered page (it may be in the title or an
              image&apos;s description).
            </MessageBarBody>
            <MessageBarActions>
              <Button size="small" onClick={() => choose('source')}>
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
              <HtmlViewer
                key={path}
                html={rendered ?? text}
                target={words}
                onMarked={onMarked}
                label="Rendered page"
              />
            ) : (
              <TextViewer
                key={`${path}:${mode}`}
                total={lines.length}
                loadLines={loadLines}
                tokens={colour}
                theme={isDark ? vscodeDark : vscodeLight}
                target={target}
                label="Page source"
              />
            )}
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
