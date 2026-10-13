/**
 * Finds words in the source of a Markdown file. A search runs on the words without the markup, so
 * both sides are compared with the markup characters and every space taken out, in lower case; when
 * the words occur more than once, the occurrence whose surroundings look most like the match's own
 * wins.
 */

const IGNORED = /[\s*_`~#>|\\]/;

/** @param {string} text */
const squash = (text) => {
  let out = '';
  for (const ch of text.toLowerCase()) if (!IGNORED.test(ch)) out += ch;
  return out;
};

const commonSuffix = (a, b) => {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
  return n;
};

const commonPrefix = (a, b) => {
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n++;
  return n;
};

const CONTEXT = 40;

/**
 * @param {string} text The Markdown source.
 * @param {{before?: string, matched: string, after?: string}} match
 * @returns {{offset: number, end: number, line: number, column: number} | null} Where the words
 *   are in the source: character offsets, and the line and column (both from 1).
 */
export function locateInSource(text, match) {
  const needle = squash(match.matched);
  if (!needle) return null;
  // The squashed text, and for each of its characters where it came from.
  const kept = new Int32Array(text.length);
  let hay = '';
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i].toLowerCase();
    if (IGNORED.test(ch) || ch.length !== 1) continue;
    kept[count++] = i;
    hay += ch;
  }
  const before = squash(match.before ?? '').slice(-CONTEXT);
  const after = squash(match.after ?? '').slice(0, CONTEXT);
  let best = -1;
  let bestScore = -1;
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, at + 1)) {
    const score =
      commonSuffix(before, hay.slice(Math.max(0, at - CONTEXT), at)) +
      commonPrefix(after, hay.slice(at + needle.length, at + needle.length + CONTEXT));
    if (score > bestScore) {
      best = at;
      bestScore = score;
    }
  }
  if (best === -1) return null;
  const offset = kept[best];
  const end = kept[best + needle.length - 1] + 1;
  const upTo = text.slice(0, offset);
  const lineStart = upTo.lastIndexOf('\n') + 1;
  return {
    offset,
    end,
    line: upTo.split('\n').length,
    column: offset - lineStart + 1,
  };
}
