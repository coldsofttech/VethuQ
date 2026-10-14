// The English keyboard as data: layers of rows of keys. A key is one of
//   { type: 'text', value }      types the character (shift turns a letter into its capital)
//   { type: 'shift' | 'backspace' | 'enter' | 'space' | 'close' }
//   { type: 'layer', to, label } switches layer
// `width` is the share of a row the key takes (1 is one letter).

const chars = (text) => [...text].map((value) => ({ type: 'text', value }));

const backspace = { type: 'backspace', width: 1.5 };
const bottom = [
  { type: 'space', width: 5 },
  { type: 'enter', width: 1.5 },
  { type: 'close', width: 1.5 },
];

export const LAYERS = {
  letters: [
    chars('1234567890'),
    chars('qwertyuiop'),
    chars('asdfghjkl'),
    [{ type: 'shift', width: 1.5 }, ...chars('zxcvbnm'), backspace],
    [{ type: 'layer', to: 'symbols', label: '?123', width: 1.5 }, ...chars(',.'), ...bottom],
  ],
  symbols: [
    chars('1234567890'),
    chars('-/:;()$&@"'),
    chars('[]{}#%^*+='),
    [...chars("_\\|~<>?!'"), backspace],
    [{ type: 'layer', to: 'letters', label: 'abc', width: 1.5 }, ...chars(',.'), ...bottom],
  ],
};

// Names a screen reader says for what is not a letter or a digit.
export const NAMES = {
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
