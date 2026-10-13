import markdownit from 'markdown-it';

/**
 * Markdown as safe HTML, a block at a time. Raw HTML in the text is shown as text (never as
 * markup), links are shown but cannot be followed and pictures are shown as their alt text: a
 * preview must not open anything or fetch anything.
 */
export function createMarkdown() {
  const md = markdownit({ html: false, linkify: false, typographer: false, breaks: false });
  md.renderer.rules.link_open = () => '<span class="mdv-link">';
  md.renderer.rules.link_close = () => '</span>';
  md.renderer.rules.image = (tokens, index) =>
    `<span class="mdv-image">[${md.utils.escapeHtml(tokens[index].content || 'image')}]</span>`;
  return md;
}

/**
 * The top-level blocks of a text (a heading, a paragraph, a whole list, a code block, a table...),
 * each with the lines it covers: `start` (0-based) up to `end` (not included).
 *
 * @param {ReturnType<typeof createMarkdown>} md
 * @param {string} text
 * @returns {Array<{start: number, end: number, tokens: object[]}>}
 */
export function blocksOf(md, text) {
  const tokens = md.parse(text, {});
  const blocks = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.level !== 0 || !token.map) continue;
    let last = i;
    if (token.nesting === 1) {
      while (last < tokens.length && !(tokens[last].level === 0 && tokens[last].nesting === -1)) {
        last++;
      }
    }
    blocks.push({ start: token.map[0], end: token.map[1], tokens: tokens.slice(i, last + 1) });
    i = last;
  }
  return blocks;
}

/** The index of the block that holds source line `line` (0-based), or the one just before it. */
export function blockAt(blocks, line) {
  let low = 0;
  let high = blocks.length - 1;
  let found = 0;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (blocks[middle].start <= line) {
      found = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  return found;
}

/** A block as HTML. */
export const render = (md, block) => md.renderer.render(block.tokens, md.options, {});
