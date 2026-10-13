/**
 * An HTML tokenizer for colouring a page line by line, a formatter for minified pages, and a way to
 * find words as a reader sees them (without the tags).
 *
 * Like `css.js`, a line is coloured knowing only the state at its start (inside a comment, a tag,
 * a quoted attribute value, a `<style>` or `<script>` block), so a window of lines can be coloured
 * in any order. A `<style>` block's content is coloured by the CSS tokenizer.
 */
import { START as CSS_START, formatCss, scan as scanCss } from './css.js';

const RAW = new Set(['style', 'script']);
const VOID = new Set([
  'area',
  'base',
  'br',
  'col',
  'embed',
  'hr',
  'img',
  'input',
  'link',
  'meta',
  'param',
  'source',
  'track',
  'wbr',
]);

const interned = new Map();
const cssIds = new Map();
const cssId = (css) => {
  if (!cssIds.has(css)) cssIds.set(css, cssIds.size);
  return cssIds.get(css);
};
const state = (mode, quote, tag, closing, css) => {
  const key = `${mode}|${quote}|${tag}|${closing ? 1 : 0}|${cssId(css)}`;
  let found = interned.get(key);
  if (!found) {
    found = { mode, quote, tag, closing, css };
    interned.set(key, found);
  }
  return found;
};

/** The state at the start of a page. */
export const START = state('text', '', '', false, CSS_START);

/**
 * Colours one line.
 *
 * @param {string} line
 * @param {object} from The state at the start of the line.
 * @param {boolean} [collect] Make the segments (false: only find the state at the end).
 * @returns {{segments: Array<[string | null, string]> | null, state: object}}
 */
export function scan(line, from, collect = true) {
  let { mode, quote, tag, closing, css } = from;
  const segments = collect ? [] : null;
  const push = (kind, text) => {
    if (!collect || !text) return;
    const last = segments[segments.length - 1];
    if (last && last[0] === kind) last[1] += text;
    else segments.push([kind, text]);
  };
  let i = 0;
  while (i < line.length) {
    if (mode === 'comment') {
      const end = line.indexOf('-->', i);
      push('comment', end === -1 ? line.slice(i) : line.slice(i, end + 3));
      if (end === -1) i = line.length;
      else {
        i = end + 3;
        mode = 'text';
      }
      continue;
    }
    if (mode === 'style' || mode === 'script') {
      const close = line.toLowerCase().indexOf(`</${mode}`, i);
      const stop = close === -1 ? line.length : close;
      const inside = line.slice(i, stop);
      if (inside) {
        if (mode === 'style') {
          const result = scanCss(inside, css, collect);
          for (const [kind, text] of result.segments ?? []) push(kind, text);
          css = result.state;
        } else push(null, inside);
      }
      i = stop;
      if (close !== -1) {
        mode = 'text';
        css = CSS_START;
      }
      continue;
    }
    if (mode === 'tag') {
      const ch = line[i];
      if (quote) {
        const end = line.indexOf(quote, i);
        push('attrvalue', line.slice(i, end === -1 ? line.length : end + 1));
        if (end === -1) i = line.length;
        else {
          i = end + 1;
          quote = '';
        }
      } else if (/\s/.test(ch)) {
        let j = i + 1;
        while (j < line.length && /\s/.test(line[j])) j++;
        push(null, line.slice(i, j));
        i = j;
      } else if (ch === '>' || (ch === '/' && line[i + 1] === '>')) {
        const end = ch === '>' ? i + 1 : i + 2;
        push('tagpunct', line.slice(i, end));
        i = end;
        mode = !closing && RAW.has(tag) && ch === '>' ? tag : 'text';
        css = CSS_START;
      } else if (ch === '=') {
        push('tagpunct', ch);
        i++;
        let j = i;
        while (j < line.length && /\s/.test(line[j])) j++;
        push(null, line.slice(i, j));
        i = j;
        if (line[i] === '"' || line[i] === "'") {
          quote = line[i];
          push('attrvalue', quote);
          i++;
        } else {
          let k = i;
          while (
            k < line.length &&
            !/[\s>]/.test(line[k]) &&
            !(line[k] === '/' && line[k + 1] === '>')
          )
            k++;
          push('attrvalue', line.slice(i, k));
          i = k;
        }
      } else {
        let j = i;
        while (
          j < line.length &&
          !/[\s=>]/.test(line[j]) &&
          !(line[j] === '/' && line[j + 1] === '>')
        )
          j++;
        push('attribute', line.slice(i, j === i ? i + 1 : j));
        i = j === i ? i + 1 : j;
      }
      continue;
    }
    // Text, or the start of a tag, comment or doctype.
    const open = line.indexOf('<', i);
    const stop = open === -1 ? line.length : open;
    let from_ = i;
    for (const entity of line.slice(i, stop).matchAll(/&(#\d+|#x[0-9a-fA-F]+|\w+);/g)) {
      const at = i + entity.index;
      push(null, line.slice(from_, at));
      push('entity', entity[0]);
      from_ = at + entity[0].length;
    }
    push(null, line.slice(from_, stop));
    i = stop;
    if (open === -1) break;
    if (line.startsWith('<!--', i)) {
      mode = 'comment';
      push('comment', '<!--');
      i += 4;
    } else if (line[i + 1] === '!' || line[i + 1] === '?') {
      const end = line.indexOf('>', i);
      push('doctype', line.slice(i, end === -1 ? line.length : end + 1));
      i = end === -1 ? line.length : end + 1;
    } else if (/[a-zA-Z/]/.test(line[i + 1] ?? '')) {
      closing = line[i + 1] === '/';
      const nameFrom = i + (closing ? 2 : 1);
      let j = nameFrom;
      while (j < line.length && /[^\s/>]/.test(line[j])) j++;
      push('tagpunct', line.slice(i, nameFrom));
      push('tag', line.slice(nameFrom, j));
      tag = line.slice(nameFrom, j).toLowerCase();
      i = j;
      mode = 'tag';
    } else {
      push(null, '<');
      i++;
    }
  }
  return { segments, state: state(mode, quote, tag, closing, css) };
}

/** Colours a page's lines, whichever are asked for, in any order. */
export class HtmlHighlighter {
  /** @param {string[]} lines */
  constructor(lines) {
    this.lines = lines;
    this.starts = [START];
  }

  /** The `[kind, text]` pieces of line `index` (0-based). */
  segments(index) {
    for (let k = this.starts.length - 1; k < index; k++) {
      this.starts[k + 1] = scan(this.lines[k], this.starts[k], false).state;
    }
    return scan(this.lines[index], this.starts[index]).segments;
  }
}

/**
 * A page with each tag on its own line, indented by element. The inside of `<pre>`, `<textarea>`
 * and `<script>` is left as written; a `<style>` block is laid out as CSS.
 *
 * @param {string} html
 * @returns {string}
 */
export function formatHtml(html) {
  const out = [];
  let depth = 0;
  const put = (text) => {
    const line = text.trim();
    if (line) out.push('  '.repeat(Math.max(0, depth)) + line);
  };
  const pattern =
    /<!--[\s\S]*?-->|<![^>]*>|<\?[^>]*>|<\/?[a-zA-Z][^\s/>]*(?:"[^"]*"|'[^']*'|[^>"'])*>/g;
  let at = 0;
  let verbatim = '';
  for (let found = pattern.exec(html); found; found = pattern.exec(html)) {
    const text = html.slice(at, found.index);
    const tag = found[0];
    at = found.index + tag.length;
    const name = (/^<\/?([a-zA-Z][^\s/>]*)/.exec(tag)?.[1] ?? '').toLowerCase();
    const closing = tag.startsWith('</');
    if (verbatim) {
      if (closing && name === verbatim) {
        if (verbatim === 'style') {
          for (const row of formatCss(text).split('\n')) {
            if (row.trim()) out.push('  '.repeat(depth) + row);
          }
        } else if (text.trim()) out.push(text.replace(/\s+$/, ''));
        depth = Math.max(0, depth - 1);
        put(tag);
        verbatim = '';
      }
      continue;
    }
    put(text.replace(/\s+/g, ' '));
    if (tag.startsWith('<!') || tag.startsWith('<?')) {
      put(tag.startsWith('<!--') ? tag.replace(/\s*\n\s*/g, ' ') : tag);
    } else if (closing) {
      depth = Math.max(0, depth - 1);
      put(tag);
    } else {
      put(tag.replace(/\s+/g, ' '));
      if (!VOID.has(name) && !tag.endsWith('/>')) {
        depth++;
        if (name === 'style' || name === 'script' || name === 'pre' || name === 'textarea') {
          verbatim = name;
        }
      }
    }
  }
  put(html.slice(at).replace(/\s+/g, ' '));
  return out.join('\n');
}

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

const decode = (entity) => {
  const body = entity.slice(1, -1);
  if (body[0] === '#') {
    const code =
      body[1] === 'x' || body[1] === 'X' ? parseInt(body.slice(2), 16) : Number(body.slice(1));
    try {
      return String.fromCodePoint(code);
    } catch {
      return null;
    }
  }
  return ENTITIES[body] ?? null;
};

/**
 * Finds words in the source of a page as a reader sees them: tags, comments, scripts and styles
 * do not count, and entities are the characters they stand for. Compared with the spaces taken
 * out and in lower case; when the words occur more than once, the occurrence whose surroundings
 * look most like the match's own wins.
 *
 * @param {string} html
 * @param {{before?: string, matched: string, after?: string}} match
 * @returns {{offset: number, end: number, line: number, column: number} | null} Where the words
 *   are in the source: offsets (of the first and after the last of their characters), line and
 *   column (from 1).
 */
export function locateInHtml(html, match) {
  const squash = (text) => text.toLowerCase().replace(/\s+/g, '');
  const needle = squash(match.matched);
  if (!needle) return null;
  const kept = new Int32Array(html.length);
  let hay = '';
  let count = 0;
  const add = (text, offset) => {
    for (const ch of text.toLowerCase()) {
      if (/\s/.test(ch) || ch.length !== 1) continue;
      kept[count++] = offset;
      hay += ch;
    }
  };
  for (let i = 0; i < html.length;) {
    if (html.startsWith('<!--', i)) {
      const end = html.indexOf('-->', i + 4);
      i = end === -1 ? html.length : end + 3;
    } else if (html[i] === '<' && /[a-zA-Z/!?]/.test(html[i + 1] ?? '')) {
      const name = /^<([a-zA-Z]+)/.exec(html.slice(i, i + 12))?.[1]?.toLowerCase();
      const end = html.indexOf('>', i);
      i = end === -1 ? html.length : end + 1;
      if (name && RAW.has(name)) {
        const close = html.toLowerCase().indexOf(`</${name}`, i);
        i = close === -1 ? html.length : close;
      }
    } else if (html[i] === '&') {
      const entity = /^&(#\d+|#x[0-9a-fA-F]+|\w+);/.exec(html.slice(i, i + 12));
      const decoded = entity ? decode(entity[0]) : null;
      if (decoded !== null) {
        add(decoded, i);
        i += entity[0].length;
      } else {
        add('&', i);
        i++;
      }
    } else {
      add(html[i], i);
      i++;
    }
  }
  const same = (a, b, fromEnd) => {
    let n = 0;
    while (
      n < a.length &&
      n < b.length &&
      (fromEnd ? a.at(-1 - n) === b.at(-1 - n) : a[n] === b[n])
    )
      n++;
    return n;
  };
  const before = squash(match.before ?? '').slice(-40);
  const after = squash(match.after ?? '').slice(0, 40);
  let best = -1;
  let bestScore = -1;
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, at + 1)) {
    const score =
      same(before, hay.slice(Math.max(0, at - 40), at), true) +
      same(after, hay.slice(at + needle.length, at + needle.length + 40), false);
    if (score > bestScore) {
      best = at;
      bestScore = score;
    }
  }
  if (best === -1) return null;
  const offset = kept[best];
  const end = kept[best + needle.length - 1] + 1;
  const upTo = html.slice(0, offset);
  return {
    offset,
    end,
    line: upTo.split('\n').length,
    column: offset - (upTo.lastIndexOf('\n') + 1) + 1,
  };
}
