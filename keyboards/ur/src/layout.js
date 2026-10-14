import {
  PUNCTUATION_NAMES,
  backspaceKey,
  bottomRow,
  keys,
  shiftKey,
  symbolsLayer,
} from '@vethuq/keyboard-shared';

// Urdu in Urdu script, laid out by sound on a QWERTY keyboard (q is ق, t is ت, s is س ...), the
// letter of a sound on its key and, with shift, its kin (ت and ٹ, د and ڈ, ر and ڑ, ہ and ھ, ا and
// آ, ء and ئ). The row of digits is Urdu, and with shift ASCII (documents hold both); the symbols
// layer has the ASCII digits. The keys sit where the physical keys are, left to right, though the
// text runs right to left.

const toSymbols = { type: 'layer', to: 'symbols', label: '?123', name: 'Numbers and symbols' };
const toLetters = { type: 'layer', to: 'letters', label: 'ابپ', name: 'Letters' };

export const LAYERS = {
  letters: [
    [...keys('\u064E', '\u0651'), ...keys('۱۲۳۴۵۶۷۸۹۰', '1234567890'), ...keys('\u0650', '\u0652')],
    keys('قوعرتےءیہپچں', 'غؤظڑٹ\u0670ئ\u0653ھثژ\u0654'),
    [...keys('اسدفگ', 'آصڈذ؛'), ...keys('حجکلخط'), ...keys('ض', '\u064F')],
    [shiftKey, ...keys('زشبنم،۔؟'), backspaceKey],
    bottomRow(toSymbols),
  ],
  symbols: symbolsLayer('1234567890', toLetters),
};

// What a screen reader says for the signs and the Urdu punctuation.
export const NAMES = {
  ...PUNCTUATION_NAMES,
  '\u064E': 'zabar',
  '\u0650': 'zer',
  '\u064F': 'pesh',
  '\u0651': 'shadda',
  '\u0652': 'jazm',
  '\u0670': 'khari zabar',
  '\u0653': 'maddah',
  '\u0654': 'hamza above',
  '،': 'Urdu comma',
  '۔': 'Urdu full stop',
  '؟': 'Urdu question mark',
  '؛': 'Urdu semicolon',
};
