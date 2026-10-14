import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const keysOf = (layer) => LAYERS[layer].flat().filter((key) => key.type === 'text');
const typable = (layer) => keysOf(layer).flatMap((key) => [key.value, key.shift].filter(Boolean));

const LETTERS = 'ابپتٹثجچحخدڈذرڑزژسشصضطظعغفقکگلمنںوؤہھءئیےآ';
const SIGNS = 'َُِّْٰٓٔ';
const PUNCTUATION = '،۔؟؛';

describe('the Urdu layout', () => {
  it('reaches every letter, sign and Urdu punctuation mark, each on one key', () => {
    const all = typable('letters');
    for (const char of [...LETTERS, ...SIGNS, ...PUNCTUATION]) {
      expect(
        all.filter((c) => c === char),
        char,
      ).toHaveLength(1);
    }
  });

  it('has the Urdu digits on the row of digits, the ASCII digits with shift, and on the symbols layer', () => {
    const row = LAYERS.letters[0].filter((key) => /[۰-۹]/.test(key.value));
    expect(row.map((key) => key.value).join('')).toBe('۱۲۳۴۵۶۷۸۹۰');
    expect(row.map((key) => key.shift).join('')).toBe('1234567890');
    expect(
      typable('symbols')
        .filter((c) => /\d/.test(c))
        .join(''),
    ).toBe('1234567890');
  });

  it('shifts a key to a different character that is not ASCII, apart from the digits', () => {
    for (const key of keysOf('letters')) {
      if (key.shift && !/\d/.test(key.shift)) {
        expect(key.shift).not.toBe(key.value);
        expect(/[\u0600-\u06FF]/.test(key.shift), key.shift).toBe(true);
      }
    }
  });

  it('does not put a character on two keys of a layer', () => {
    for (const layer of ['letters', 'symbols']) {
      const all = typable(layer);
      expect(new Set(all).size).toBe(all.length);
    }
  });

  it('names every sign and symbol that a screen reader could not say on its own', () => {
    for (const layer of ['letters', 'symbols']) {
      for (const value of typable(layer).filter((c) => /[\p{M}\p{P}\p{S}]/u.test(c))) {
        expect(NAMES[value], value).toBeTruthy();
      }
    }
  });
});
