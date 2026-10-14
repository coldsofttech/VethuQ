import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

// Telugu on the InScript layout (the standard one of Windows, Android and iOS): vowel signs and
// vowels on the left hand's keys, consonants on the right's, the vowel sign on a key and its vowel
// on the same key with shift. The row of digits is Telugu, and with shift ASCII (documents hold
// both); the symbols layer has the ASCII digits.

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toLetters = { type: 'layer', to: 'letters', label: 'అఆ', name: 'Letters' };

export const LAYERS = {
  letters: [
    [...keys('ొ', 'ఒ'), ...keys('౧౨౩౪౫౬౭౮౯౦', '1234567890'), ...keys('ఞ', 'ౠ')],
    keys('ౌైాీూబహగదజడృ', 'ఔఐఆఈఊభఙఘధఝఢఋ'),
    keys('ోే్ిుపరకతచటయ', 'ఓఏఅఇఉఫఱఖథఛఠౄ'),
    [shiftKey, ...keys('ెంమనవలసష', 'ఎఁణఃఴళశఽ'), backspaceKey],
    bottomRow(toSymbols),
  ],
  symbols: symbolsLayer('1234567890', toLetters),
};

// What a screen reader says for the signs, which are not letters of their own.
export const NAMES = {
  ...PUNCTUATION_NAMES,
  'ొ': 'short o sign',
  'ౌ': 'au sign',
  'ై': 'ai sign',
  'ా': 'aa sign',
  'ీ': 'ii sign',
  'ూ': 'uu sign',
  'ృ': 'vocalic r sign',
  'ౄ': 'long vocalic r sign',
  'ో': 'oo sign',
  'ే': 'ee sign',
  '్': 'virama',
  'ి': 'i sign',
  'ు': 'u sign',
  'ె': 'short e sign',
  'ం': 'anusvara',
  'ః': 'visarga',
  'ఁ': 'candrabindu',
  ఽ: 'avagraha',
};
