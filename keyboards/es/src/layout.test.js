import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const keysOf = (layer) => LAYERS[layer].flat().filter((key) => key.type === 'text');
const typable = (layer) => keysOf(layer).flatMap((key) => [key.value, key.shift].filter(Boolean));

const LETTERS = 'abcdefghijklmnopqrstuvwxyzñáéíóúü';

describe('the Spanish layout', () => {
  it('has the letters in QWERTY order, with ñ after l', () => {
    const row = (i) =>
      LAYERS.letters[i]
        .filter((key) => key.type === 'text')
        .map((key) => key.value)
        .join('');
    expect(row(1)).toBe('qwertyuiopéú');
    expect(row(2)).toBe('asdfghjklñáí');
    expect(row(3)).toBe('zxcvbnmó');
  });

  it('reaches every letter of Spanish, with its capital, each on one key', () => {
    const all = typable('letters');
    for (const letter of LETTERS) {
      expect(
        all.filter((c) => c === letter),
        letter,
      ).toHaveLength(1);
      expect(
        all.filter((c) => c === letter.toUpperCase()),
        letter.toUpperCase(),
      ).toHaveLength(1);
    }
  });

  it('shifts every letter to its capital and nothing else', () => {
    for (const key of keysOf('letters')) {
      if (/\p{L}/u.test(key.value)) expect(key.shift).toBe(key.value.toUpperCase());
      else expect(key.shift).toBeUndefined();
    }
  });

  it('has the digits and the inverted question and exclamation marks', () => {
    expect(
      typable('letters')
        .filter((c) => /\d/.test(c))
        .join(''),
    ).toBe('1234567890');
    expect(typable('letters')).toEqual(expect.arrayContaining(['¿', '¡']));
  });

  it('does not put a character on two keys of a layer', () => {
    for (const layer of ['letters', 'symbols']) {
      const all = typable(layer);
      expect(new Set(all).size).toBe(all.length);
    }
  });

  it('names every symbol that a screen reader could not say on its own', () => {
    for (const layer of ['letters', 'symbols']) {
      for (const value of typable(layer).filter((c) => /[\p{M}\p{P}\p{S}]/u.test(c))) {
        expect(NAMES[value], value).toBeTruthy();
      }
    }
  });
});
