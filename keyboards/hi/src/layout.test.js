import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const keysOf = (layer) => LAYERS[layer].flat().filter((key) => key.type === 'text');
const typable = (layer) => keysOf(layer).flatMap((key) => [key.value, key.shift].filter(Boolean));

const VOWELS = 'अआइईउऊऋएऐओऔऑऎऒ';
const CONSONANTS = 'कखगघङचछजझञटठडढणतथदधनपफबभमयरऱलळवशषसहऩऴ';
const SIGNS = 'ािीुूृॆेैॊोौॉ्ंःँ़।';

describe('the Hindi layout', () => {
  it('reaches every vowel, consonant and sign, each on one key', () => {
    const all = typable('letters');
    for (const letter of [...VOWELS, ...CONSONANTS, ...SIGNS]) {
      expect(
        all.filter((c) => c === letter),
        letter,
      ).toHaveLength(1);
    }
  });

  it('has the Devanagari digits on the row of digits, the ASCII digits with shift, and on the symbols layer', () => {
    const row = LAYERS.letters[0].filter((key) => /[०-९]/.test(key.value));
    expect(row.map((key) => key.value).join('')).toBe('१२३४५६७८९०');
    expect(row.map((key) => key.shift).join('')).toBe('1234567890');
    expect(
      typable('symbols')
        .filter((c) => /\d/.test(c))
        .join(''),
    ).toBe('1234567890');
  });

  it('shifts a key to a different Devanagari character, and only letters have a shift', () => {
    for (const key of keysOf('letters')) {
      if (key.shift && !/\d/.test(key.shift)) {
        expect(key.shift).not.toBe(key.value);
        expect(
          /\p{Script=Devanagari}/u.test(key.value) && /\p{Script=Devanagari}/u.test(key.shift),
        ).toBe(true);
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
