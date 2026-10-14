import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  cased,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

// Spanish on QWERTY with ñ, the Spanish layout: the accented vowels and ü on keys of their own, ¿
// and ¡ by the full stop. The row of digits is ASCII, with no shift needed.

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toLetters = { type: 'layer', to: 'letters', label: 'abc', name: 'Letters' };

export const LAYERS = {
  letters: [
    [...keys('1234567890'), ...cased('ü')],
    cased('qwertyuiopéú'),
    cased('asdfghjklñáí'),
    [shiftKey, ...cased('zxcvbnmó'), backspaceKey],
    bottomRow(toSymbols, ',.¿¡'),
  ],
  symbols: symbolsLayer('1234567890', toLetters),
};

export const NAMES = {
  ...PUNCTUATION_NAMES,
  '¿': 'inverted question mark',
  '¡': 'inverted exclamation mark',
};
