import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

/** Lines are fetched in chunks of this many, so scrolling asks for few, large requests. */
export const CHUNK = 200;
const OVERSCAN = 20;

const FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace';

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

/** One line, with `mark` (`{from, to}` in characters) marked when given. */
function Line({ number, text, mark, current, top, height, digits }) {
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
        background: current ? 'var(--colorNeutralBackground1Hover, #f5f5f5)' : undefined,
      }}
    >
      <span style={{ ...css.gutter, width: `${digits + 2}ch`, height }} aria-hidden="true">
        {number}
      </span>
      <span style={css.text}>
        {mark ? (
          <>
            {text.slice(0, mark.from)}
            <mark style={css.hit}>{text.slice(mark.from, mark.to)}</mark>
            {text.slice(mark.to)}
          </>
        ) : (
          text
        )}
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
 * @param {string} [props.label] The accessible name.
 */
export function TextViewer({ total, loadLines, target, lineHeight = 20, label = 'Text' }) {
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
          mark={mark}
          current={Boolean(here)}
          top={index * lineHeight}
          height={lineHeight}
          digits={digits}
        />,
      );
    }
    return out;
  }, [chunks, first, last, target, lineHeight, digits]);

  return (
    <div
      ref={root}
      role="table"
      aria-label={label}
      style={css.root}
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
