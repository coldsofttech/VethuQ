import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toLetters = { type: 'layer', to: 'letters', label: 'abc', name: 'Letters' };

export const LAYERS = {
  letters: [
    keys('1234567890'),
    keys('qwertyuiop', 'QWERTYUIOP'),
    keys('asdfghjkl', 'ASDFGHJKL'),
    [shiftKey, ...keys('zxcvbnm', 'ZXCVBNM'), backspaceKey],
    bottomRow(toSymbols),
  ],
  symbols: symbolsLayer('1234567890', toLetters),
};

export const NAMES = PUNCTUATION_NAMES;
