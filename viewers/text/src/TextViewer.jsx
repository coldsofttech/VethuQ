import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { piecesOf } from './pieces.js';

/** Lines are fetched in chunks of this many, so scrolling asks for few, large requests. */
export const CHUNK = 200;
const OVERSCAN = 20;

// The script fonts are the ones the host bundles (they come ahead of the monospace fonts, which have
// no Devanagari, Telugu or Urdu letters); a page without them falls back to the system's.
const FONT =
  'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, "Noto Nastaliq Urdu", ' +
  '"Noto Sans Devanagari", "Noto Sans Telugu", monospace';

// Colours come from the host's theme variables when it has them (Fluent UI sets these), else defaults.
const css = {
  root: {
    position: 'relative',
    height: '100%',
    overflow: 'auto',
    fontFamily: FONT,
    fontSize: 13,
    background: 'var(--colorNeutralBackground1, #fff)',
    color: 'var(--colorNeutralForeground1, #242424)',
  },
  gutter: {
    position: 'sticky',
    left: 0,
    display: 'inline-block',
    boxSizing: 'border-box',
    padding: '0 12px 0 8px',
    textAlign: 'right',
    userSelect: 'none',
    color: 'var(--colorNeutralForeground3, #707070)',
    background: 'var(--colorNeutralBackground2, #fafafa)',
    borderRight: '1px solid var(--colorNeutralStroke2, #e0e0e0)',
  },
  text: { paddingLeft: 12, whiteSpace: 'pre' },
  hit: {
    background: 'rgba(255, 196, 0, 0.45)',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
    borderRadius: 2,
  },
};

/** One line, with `mark` (`{from, to}` in characters) marked and `segments` coloured, when given. */
function Line({ number, text, segments, mark, current, top, height, digits, theme, colors }) {
  const hit = theme
    ? { ...css.hit, background: theme.hitBackground, outline: `1px solid ${theme.hitOutline}` }
    : css.hit;
  return (
    <div
      role="row"
      data-line={number}
      style={{
        position: 'absolute',
        top,
        height,
        lineHeight: `${height}px`,
        minWidth: '100%',
        width: 'max-content',
        background: current
          ? (theme?.currentLine ?? 'var(--colorNeutralBackground1Hover, #f5f5f5)')
          : undefined,
      }}
    >
      <span
        style={{
          ...css.gutter,
          ...(theme && {
            color: theme.gutterForeground,
            background: theme.gutterBackground,
            borderRight: `1px solid ${theme.gutterBorder}`,
          }),
          width: `${digits + 2}ch`,
          height,
        }}
        aria-hidden="true"
      >
        {number}
      </span>
      <span style={css.text}>
        {segments || mark
          ? piecesOf(text, segments, mark).map((piece, i) => {
              const style = piece.kind && colors ? { color: colors[piece.kind] } : undefined;
              return piece.hit ? (
                <mark key={i} style={{ ...hit, ...style }}>
                  {piece.text}
                </mark>
              ) : (
                <span key={i} style={style}>
                  {piece.text}
                </span>
              );
            })
          : text}
      </span>
    </div>
  );
}

/**
 * A read-only view of a large text. Only the lines in view are in the page, and `loadLines` is
 * asked for the rest in chunks as they scroll near, so a file of millions of lines opens at once.
 *
 * @param {object} props
 * @param {number} props.total How many lines the text has.
 * @param {(start: number, count: number) => Promise<string[]>} props.loadLines The lines from
 *   `start` (0-based); fewer than `count` only at the end.
 * @param {{line: number, column?: number | null, length?: number}} [props.target] A line (from 1)
 *   to scroll to and the words on it to mark. Moving it scrolls again.
 * @param {number} [props.lineHeight] The height of every line, in pixels.
 * @param {(text: string, index: number) => Array<[string, string]> | null} [props.tokens] Colours a
 *   line: its `[kind, text]` pieces, which make up the line (null: draw it plain).
 * @param {{editor: object, tokens: Record<string, string>}} [props.theme] The editor's colours and
 *   the colour of each kind of token (`vscodeDark`, `vscodeLight`); default: the page's own.
 * @param {string} [props.label] The accessible name.
 */
export function TextViewer({
  total,
  loadLines,
  target,
  lineHeight = 20,
  tokens,
  theme,
  label = 'Text',
}) {
  const root = useRef(null);
  const [chunks, setChunks] = useState(() => new Map());
  const asked = useRef(new Set());
  const [view, setView] = useState({ top: 0, height: 0 });
  const [failure, setFailure] = useState(null);
  const digits = String(Math.max(1, total)).length;

  // A different text starts again.
  const source = useRef(loadLines);
  useEffect(() => {
    if (source.current === loadLines) return;
    source.current = loadLines;
    asked.current = new Set();
    setChunks(new Map());
    setFailure(null);
  }, [loadLines]);

  const measure = useCallback(() => {
    const element = root.current;
    if (element) setView({ top: element.scrollTop, height: element.clientHeight });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = root.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  const first = Math.max(0, Math.floor(view.top / lineHeight) - OVERSCAN);
  const last = Math.min(total - 1, Math.ceil((view.top + view.height) / lineHeight) + OVERSCAN);

  // Ask for the chunks that hold the lines in view.
  useEffect(() => {
    if (total <= 0 || last < first || !view.height) return;
    // The view is about to be measured again (a scroll is under way): wait for it.
    if (root.current && Math.abs(root.current.scrollTop - view.top) > 1) return;
    for (let chunk = Math.floor(first / CHUNK); chunk <= Math.floor(last / CHUNK); chunk++) {
      if (asked.current.has(chunk)) continue;
      asked.current.add(chunk);
      const load = loadLines;
      load(chunk * CHUNK, CHUNK).then(
        (lines) => {
          if (source.current !== load) return;
          setChunks((current) => new Map(current).set(chunk, lines));
        },
        (error) => {
          if (source.current !== load) return;
          asked.current.delete(chunk);
          setFailure(error);
        },
      );
    }
  }, [first, last, total, loadLines, view.top, view.height]);

  // Scroll so the target line is in the middle of the view.
  const scrolled = useRef(null);
  useLayoutEffect(() => {
    const element = root.current;
    if (!target || !element || !view.height) return;
    const key = `${target.line}:${target.column ?? ''}:${loadLines === source.current ? '' : 'x'}`;
    if (scrolled.current === key) return;
    scrolled.current = key;
    element.scrollTop = Math.max(
      0,
      (target.line - 1) * lineHeight - (view.height - lineHeight) / 2,
    );
    measure();
  }, [target, view.height, lineHeight, loadLines, measure]);

  // Once the target's line is drawn, bring its marked words into view sideways too.
  const sideways = useRef(null);
  useLayoutEffect(() => {
    const element = root.current;
    if (!target || !element) return;
    const key = `${target.line}:${target.column ?? ''}:${target.length ?? ''}`;
    if (sideways.current === key) return;
    const mark = element.querySelector('mark');
    if (!mark) return;
    sideways.current = key;
    const box = element.getBoundingClientRect();
    const at = mark.getBoundingClientRect();
    if (at.right > box.right - 24 || at.left < box.left + 80) {
      element.scrollLeft += at.left - box.left - box.width / 3;
    }
  }, [target, chunks, view]);

  const rows = useMemo(() => {
    const out = [];
    for (let index = first; index <= last; index++) {
      const lines = chunks.get(Math.floor(index / CHUNK));
      const text = lines?.[index % CHUNK];
      if (text === undefined) continue;
      const number = index + 1;
      const here = target && target.line === number;
      const from = here && target.column ? target.column - 1 : null;
      const mark =
        from !== null && target.length
          ? { from, to: Math.min(text.length, from + target.length) }
          : null;
      out.push(
        <Line
          key={number}
          number={number}
          text={text}
          segments={tokens ? tokens(text, index) : null}
          theme={theme?.editor}
          colors={theme?.tokens}
          mark={mark}
          current={Boolean(here)}
          top={index * lineHeight}
          height={lineHeight}
          digits={digits}
        />,
      );
    }
    return out;
  }, [chunks, first, last, target, lineHeight, digits, tokens, theme]);

  return (
    <div
      ref={root}
      role="table"
      aria-label={label}
      style={{
        ...css.root,
        ...(theme && { background: theme.editor.background, color: theme.editor.foreground }),
      }}
      onScroll={measure}
      tabIndex={0}
    >
      <div
        style={{
          position: 'relative',
          height: total * lineHeight,
          minWidth: '100%',
        }}
      >
        {rows}
      </div>
      {failure && (
        <div role="alert" style={{ position: 'sticky', bottom: 0, padding: 8 }}>
          The text could not be loaded: {failure.message}
        </div>
      )}
    </div>
  );
}
