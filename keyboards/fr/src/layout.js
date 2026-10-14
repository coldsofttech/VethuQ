import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  cased,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

// French on AZERTY, the French layout: the letters where a French keyboard has them, with é è à ù ç
// ê on keys of their own. The other accented letters, the ligatures and the French quotation marks
// are on a second layer. The row of digits is ASCII, with no shift needed.

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toAccents = { type: 'layer', to: 'accents', label: 'âô', name: 'Accented letters' };
const toLetters = { type: 'layer', to: 'letters', label: 'abc', name: 'Letters' };

export const LAYERS = {
  letters: [
    keys('1234567890'),
    cased('azertyuiopéè'),
    cased('qsdfghjklmàù'),
    [shiftKey, ...cased('wxcvbnçê'), backspaceKey],
    bottomRow([toSymbols, toAccents]),
  ],
  accents: [cased('âîôûäëïöüÿœæ'), [shiftKey, ...keys('«»’€'), backspaceKey], bottomRow(toLetters)],
  symbols: symbolsLayer('1234567890', toLetters),
};

export const NAMES = {
  ...PUNCTUATION_NAMES,
  '«': 'opening guillemet',
  '»': 'closing guillemet',
  '’': 'apostrophe',
  '€': 'euro',
};
