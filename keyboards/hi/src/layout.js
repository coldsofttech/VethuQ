import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

// Hindi (Devanagari) on the InScript layout, the standard one of Windows, Android and iOS: vowel
// signs and vowels on the left hand's keys, consonants on the right's, the vowel sign on a key and
// its vowel on the same key with shift. The row of digits is Devanagari, and with shift ASCII
// (documents hold both); the symbols layer has the ASCII digits. The danda is by the full stop.

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toLetters = { type: 'layer', to: 'letters', label: 'अआ', name: 'Letters' };

export const LAYERS = {
  letters: [
    [...keys('ॊ', 'ऒ'), ...keys('१२३४५६७८९०', '1234567890'), ...keys('ृ', 'ऋ')],
    keys('ौैाीूबहगदजड़', 'औऐआईऊभङघधझढञ'),
    keys('ोे्िुपरकतचटॉ', 'ओएअइउफऱखथछठऑ'),
    [shiftKey, ...keys('ॆंमनवलसषय', 'ऎँणऩऴळशः'), backspaceKey],
    bottomRow(toSymbols, ',।.'),
  ],
  symbols: symbolsLayer('1234567890', toLetters),
};

// What a screen reader says for the signs, which are not letters of their own.
export const NAMES = {
  ...PUNCTUATION_NAMES,
  '।': 'danda',
  'ॊ': 'short o sign',
  'ौ': 'au sign',
  'ै': 'ai sign',
  'ा': 'aa sign',
  'ी': 'ii sign',
  'ू': 'uu sign',
  'ृ': 'vocalic r sign',
  'ो': 'o sign',
  'े': 'e sign',
  '्': 'halant',
  'ि': 'i sign',
  'ु': 'u sign',
  'ॆ': 'short e sign',
  'ॉ': 'candra o sign',
  'ं': 'anusvara',
  'ः': 'visarga',
  'ँ': 'candrabindu',
  '़': 'nukta',
};
