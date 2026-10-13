const IGNORED = /[\s*_`~#>|\\]/;

/** Takes the marks made by `markIn` out again. */
export function clearMarks(root) {
  for (const mark of root.querySelectorAll('mark[data-mdv-hit]')) {
    const parent = mark.parentNode;
    mark.replaceWith(...mark.childNodes);
    parent.normalize();
  }
}

/**
 * Marks `matched` in the text a block shows (ignoring spaces, case and what formatting splits the
 * words across). With the words more than once in the block, the one after `before` and before `after`.
 *
 * @param {HTMLElement} root
 * @param {{before?: string, matched: string, after?: string}} match
 * @param {{skip?: string, style?: string}} [options] `skip`: a selector for elements whose text is
 *   not looked in (scripts, styles...); `style`: inline CSS for the marks (for a document that has
 *   none of the page's own, such as the inside of a frame).
 * @returns {HTMLElement | null} The first mark, or null when the words are not in what is shown
 *   (they can be in the Markdown's link addresses, say).
 */
export function markIn(root, match, options = {}) {
  const doc = root.ownerDocument;
  const { skip, style } = options;
  const walker = doc.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */, {
    acceptNode: (node) =>
      skip && node.parentElement?.closest(skip) ? 2 /* FILTER_REJECT */ : 1 /* FILTER_ACCEPT */,
  });
  const nodes = [];
  let hay = '';
  const owner = []; // for each squashed character: [node index, offset in that node]
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue;
    nodes.push(node);
    for (let i = 0; i < text.length; i++) {
      const ch = text[i].toLowerCase();
      if (IGNORED.test(ch) || ch.length !== 1) continue;
      hay += ch;
      owner.push([nodes.length - 1, i]);
    }
  }
  let needle = '';
  for (const ch of (match.matched ?? '').toLowerCase()) if (!IGNORED.test(ch)) needle += ch;
  if (!needle) return null;
  const squash = (t) => [...(t ?? '').toLowerCase()].filter((c) => !IGNORED.test(c)).join('');
  const before = squash(match.before).slice(-40);
  const after = squash(match.after).slice(0, 40);
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
  // The text of each node the words touch, from where they start to where they end.
  const first = owner[best];
  const last = owner[best + needle.length - 1];
  const spans = [];
  for (let n = first[0]; n <= last[0]; n++) {
    const from = n === first[0] ? first[1] : 0;
    const to = n === last[0] ? last[1] + 1 : nodes[n].nodeValue.length;
    spans.push([nodes[n], from, to]);
  }
  let firstMark = null;
  for (const [node, from, to] of spans.reverse()) {
    const range = doc.createRange();
    range.setStart(node, from);
    range.setEnd(node, to);
    const mark = doc.createElement('mark');
    mark.dataset.mdvHit = '';
    if (style) mark.style.cssText = style;
    range.surroundContents(mark);
    firstMark = mark;
  }
  return firstMark;
}
