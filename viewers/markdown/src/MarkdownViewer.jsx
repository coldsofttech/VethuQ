import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { blockAt, blocksOf, createMarkdown, render } from './blocks.js';
import { clearMarks, markIn } from './mark.js';

/** Blocks are drawn (and dropped) a group at a time: a file of any length is a list of groups. */
export const GROUP = 40;
const LINE_ESTIMATE = 22;
const BLOCK_ESTIMATE = 14;
const NEAR = '1500px 0px';

const STYLE = `
.mdv { padding: 8px 20px 40px; line-height: 1.55; font-size: 14px; overflow-wrap: anywhere; }
.mdv h1, .mdv h2, .mdv h3, .mdv h4, .mdv h5, .mdv h6 { margin: 1.1em 0 0.4em; line-height: 1.25; }
.mdv h1 { font-size: 1.9em; border-bottom: 1px solid var(--colorNeutralStroke2, #e0e0e0); }
.mdv h2 { font-size: 1.5em; border-bottom: 1px solid var(--colorNeutralStroke3, #ebebeb); }
.mdv h3 { font-size: 1.25em; }
.mdv p, .mdv ul, .mdv ol, .mdv blockquote, .mdv pre, .mdv table { margin: 0 0 0.8em; }
.mdv ul, .mdv ol { padding-left: 1.6em; }
.mdv blockquote { padding: 0 1em; border-left: 3px solid var(--colorNeutralStroke1, #d1d1d1); color: var(--colorNeutralForeground3, #616161); }
.mdv code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.9em; background: var(--colorNeutralBackground3, #f0f0f0); padding: 0.1em 0.3em; border-radius: 3px; }
.mdv pre { background: var(--colorNeutralBackground3, #f5f5f5); padding: 10px 12px; border-radius: 4px; overflow-x: auto; }
.mdv pre code { background: none; padding: 0; }
.mdv table { border-collapse: collapse; }
.mdv th, .mdv td { border: 1px solid var(--colorNeutralStroke2, #e0e0e0); padding: 4px 10px; }
.mdv th { background: var(--colorNeutralBackground3, #f5f5f5); }
.mdv hr { border: 0; border-top: 1px solid var(--colorNeutralStroke2, #e0e0e0); margin: 1.2em 0; }
.mdv .mdv-link { color: var(--colorBrandForegroundLink, #0f6cbd); text-decoration: underline; cursor: default; }
.mdv .mdv-image { color: var(--colorNeutralForeground3, #707070); font-style: italic; }
.mdv mark { background: rgba(255, 196, 0, 0.5); color: inherit; border-radius: 2px; outline: 1px solid rgba(214, 140, 0, 0.8); }
`;

const estimate = (blocks) =>
  blocks.reduce((sum, b) => sum + Math.max(1, b.end - b.start) * LINE_ESTIMATE + BLOCK_ESTIMATE, 0);

/** A group of blocks: drawn when it is near the screen (or is wanted), else a gap of its height. */
function Group({ index, blocks, md, root, wanted, heights, onDrawn, first }) {
  const frame = useRef(null);
  const [near, setNear] = useState(typeof IntersectionObserver === 'undefined');
  const draw = near || wanted;
  const html = useMemo(
    () =>
      draw ? blocks.map((b, i) => `<div data-block="${first + i}">${render(md, b)}</div>`) : null,
    [draw, blocks, md, first],
  );

  useEffect(() => {
    const element = frame.current;
    if (!element || !root || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), {
      root,
      rootMargin: NEAR,
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [root]);

  // Keep the height of what was drawn, for the gap that replaces it.
  useLayoutEffect(() => {
    if (html && frame.current) heights.current.set(index, frame.current.offsetHeight);
  });
  useLayoutEffect(() => {
    if (html && wanted && frame.current) onDrawn(frame.current);
  }, [html, wanted, onDrawn]);

  if (!html) {
    const height = heights.current.get(index) ?? estimate(blocks);
    return <div ref={frame} style={{ height }} data-group={index} />;
  }
  return <div ref={frame} data-group={index} dangerouslySetInnerHTML={{ __html: html.join('') }} />;
}

/**
 * Rendered Markdown of any size. The text is parsed once; only the groups of blocks near the screen
 * are drawn, so a very long file costs no more to scroll than a short one. It can land on a source
 * line and mark words in the block that holds it.
 *
 * @param {object} props
 * @param {string} props.text The Markdown.
 * @param {{line: number, before?: string, matched: string, after?: string}} [props.target] The
 *   source line (from 1) to scroll to and the words to mark in the block there.
 * @param {(found: boolean | null) => void} [props.onMarked] Whether the words were found in what
 *   is shown (null: there is no target).
 * @param {string} [props.label]
 */
export function MarkdownViewer({ text, target, onMarked, label = 'Markdown' }) {
  const [root, setRoot] = useState(null);
  const rootRef = useRef(null);
  const attach = useCallback((element) => {
    rootRef.current = element;
    setRoot(element);
  }, []);
  const [parsed, setParsed] = useState(null);
  const heights = useRef(new Map());
  const md = useMemo(() => createMarkdown(), []);

  // Parse after the first paint, so a large file shows "Rendering" rather than a frozen window.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      const blocks = blocksOf(md, text);
      if (!cancelled) {
        heights.current = new Map();
        setParsed({ text, blocks });
      }
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [md, text]);

  const blocks = parsed?.text === text ? parsed.blocks : null;
  const groups = useMemo(() => {
    if (!blocks) return [];
    const out = [];
    for (let i = 0; i < blocks.length; i += GROUP)
      out.push({ first: i, blocks: blocks.slice(i, i + GROUP) });
    return out;
  }, [blocks]);

  const targetBlock = blocks && target ? blockAt(blocks, target.line - 1) : null;
  const targetGroup = targetBlock === null ? null : Math.floor(targetBlock / GROUP);

  // When the wanted group is drawn: mark the words and bring them (or the block) into view.
  const handled = useRef(null);
  const key = target ? `${target.line}:${target.matched}:${target.before ?? ''}` : null;
  const onDrawn = useMemo(
    () => (frame) => {
      const container = rootRef.current;
      if (!container || targetBlock === null) return;
      const at = `${key}:${blocks.length}`;
      if (handled.current === at) return;
      handled.current = at;
      clearMarks(container);
      const block = frame.querySelector(`[data-block="${targetBlock}"]`);
      if (!block) return;
      const mark = markIn(block, target);
      onMarked?.(mark !== null);
      const shown = mark ?? block;
      const inside = shown.getBoundingClientRect().top - container.getBoundingClientRect().top;
      container.scrollTop += inside - container.clientHeight / 3;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [targetBlock, key, blocks],
  );

  useEffect(() => {
    if (!target) onMarked?.(null);
  }, [target, onMarked]);

  return (
    <div
      ref={attach}
      role="document"
      aria-label={label}
      style={{
        height: '100%',
        overflow: 'auto',
        background: 'var(--colorNeutralBackground1, #fff)',
        color: 'var(--colorNeutralForeground1, #242424)',
      }}
    >
      <style>{STYLE}</style>
      {!blocks && <div style={{ padding: 16 }}>Rendering…</div>}
      <div className="mdv">
        {groups.map((g, index) => (
          <Group
            key={g.first}
            index={index}
            first={g.first}
            blocks={g.blocks}
            md={md}
            root={root}
            wanted={index === targetGroup}
            heights={heights}
            onDrawn={onDrawn}
          />
        ))}
      </div>
    </div>
  );
}
