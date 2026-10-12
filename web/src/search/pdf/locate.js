/**
 * Finds a search match in the text pdf.js drew on a page, so it can be marked.
 *
 * VethuQ and pdf.js cut a page's text differently (spaces, line ends, where words break into items),
 * so both sides are compared with every space taken out and in lower case. When the words occur
 * more than once on the page, the occurrence whose surroundings look most like the match's own
 * (the text before and after it in the result) wins.
 */

/** @param {string} text */
const squash = (text) => text.toLowerCase().replace(/\s+/g, '');

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

/**
 * @param {string[]} strings The text of each item of the page (what pdf.js drew, in order).
 * @param {{before: string, matched: string, after: string}} match
 * @returns {number[]} The indexes of the items that hold the match; none when it is not found.
 */
export function locateMatch(strings, match) {
  const needle = squash(match.matched);
  if (!needle) return [];
  let hay = '';
  const owner = [];
  strings.forEach((text, item) => {
    const squashed = squash(text);
    hay += squashed;
    for (let k = 0; k < squashed.length; k++) owner.push(item);
  });
  const before = squash(match.before ?? '');
  const after = squash(match.after ?? '');
  let best = -1;
  let bestScore = -1;
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, at + 1)) {
    const score =
      commonSuffix(before, hay.slice(0, at)) + commonPrefix(after, hay.slice(at + needle.length));
    if (score > bestScore) {
      best = at;
      bestScore = score;
    }
  }
  if (best === -1) return [];
  return [...new Set(owner.slice(best, best + needle.length))];
}
