// A keyboard layout is data: `{ [layer]: rows }`, the first layer being the one shown first. A row
// is a list of keys; a key is one of
//   { type: 'text', value, shift? }  types `value` (or `shift` while shift is on)
//   { type: 'shift' | 'backspace' | 'enter' | 'space' | 'close' }
//   { type: 'layer', to, label, name? } switches layer
// `width` is the share of a row the key takes (1 is one ordinary key).

/** Keys that type `normal`, and `shifted` (one character each) while shift is on. */
export function keys(normal, shifted = '') {
  const upper = [...shifted];
  return [...normal].map((value, i) =>
    upper[i] ? { type: 'text', value, shift: upper[i] } : { type: 'text', value },
  );
}

export const backspaceKey = { type: 'backspace', width: 1.5 };
export const shiftKey = { type: 'shift', width: 1.5 };

/**
 * The last row of every layer: a key to the other layer, `marks` (a comma and a full stop; a
 * language can add its own, such as the danda), space, enter, hide.
 */
export function bottomRow(layerKey, marks = ',.') {
  return [
    { ...layerKey, width: 1.5 },
    ...keys(marks),
    { type: 'space', width: 5 },
    { type: 'enter', width: 1.5 },
    { type: 'close', width: 1.5 },
  ];
}

/**
 * The numbers and symbols layer every language shares, but for the row of digits (so a language can
 * show its own) and the key back to its letters.
 */
export function symbolsLayer(digits, backKey) {
  return [
    keys(digits),
    keys('-/:;()$&@"'),
    keys('[]{}#%^*+='),
    [...keys("_\\|~<>?!'"), backspaceKey],
    bottomRow(backKey),
  ];
}

// What a screen reader says for the punctuation of the shared symbols layer.
export const PUNCTUATION_NAMES = {
  ',': 'comma',
  '.': 'full stop',
  '-': 'hyphen',
  '/': 'slash',
  ':': 'colon',
  ';': 'semicolon',
  '(': 'open parenthesis',
  ')': 'close parenthesis',
  $: 'dollar',
  '&': 'ampersand',
  '@': 'at sign',
  '"': 'double quote',
  '[': 'open bracket',
  ']': 'close bracket',
  '{': 'open brace',
  '}': 'close brace',
  '#': 'hash',
  '%': 'percent',
  '^': 'caret',
  '*': 'asterisk',
  '+': 'plus',
  '=': 'equals',
  _: 'underscore',
  '\\': 'backslash',
  '|': 'vertical bar',
  '~': 'tilde',
  '<': 'less than',
  '>': 'greater than',
  '?': 'question mark',
  '!': 'exclamation mark',
  "'": 'apostrophe',
};
