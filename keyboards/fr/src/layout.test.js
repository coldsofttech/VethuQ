import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const keysOf = (layer) => LAYERS[layer].flat().filter((key) => key.type === 'text');
const typable = (layer) => keysOf(layer).flatMap((key) => [key.value, key.shift].filter(Boolean));
const everywhere = () => ['letters', 'accents'].flatMap(typable);

const LETTERS = 'abcdefghijklmnopqrstuvwxyzàâäçéèêëîïôöœæùûüÿ';

describe('the French layout', () => {
  it('has the letters in AZERTY order on the first rows', () => {
    const row = (i) =>
      LAYERS.letters[i]
        .filter((key) => key.type === 'text')
        .map((key) => key.value)
        .join('');
    expect(row(1)).toBe('azertyuiopéè');
    expect(row(2)).toBe('qsdfghjklmàù');
    expect(row(3)).toBe('wxcvbnçê');
  });

  it('reaches every letter of French, with its capital, each on one key of the two layers', () => {
    const all = everywhere();
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
    for (const layer of ['letters', 'accents']) {
      for (const key of keysOf(layer)) {
        if (/\p{L}/u.test(key.value)) expect(key.shift).toBe(key.value.toUpperCase());
        else expect(key.shift).toBeUndefined();
      }
    }
  });

  it('has the digits, a way between the layers, and the French quotation marks', () => {
    expect(
      typable('letters')
        .filter((c) => /\d/.test(c))
        .join(''),
    ).toBe('1234567890');
    expect(typable('accents')).toEqual(expect.arrayContaining(['«', '»', '’', '€']));
    const to = (layer) =>
      LAYERS[layer]
        .flat()
        .filter((k) => k.type === 'layer')
        .map((k) => k.to);
    expect(to('letters')).toEqual(['symbols', 'accents']);
    expect(to('accents')).toEqual(['letters']);
    expect(to('symbols')).toEqual(['letters']);
  });

  it('does not put a character on two keys of a layer', () => {
    for (const layer of ['letters', 'accents', 'symbols']) {
      const all = typable(layer);
      expect(new Set(all).size).toBe(all.length);
    }
  });

  it('names every symbol that a screen reader could not say on its own', () => {
    for (const layer of ['letters', 'accents', 'symbols']) {
      for (const value of typable(layer).filter((c) => /[\p{M}\p{P}\p{S}]/u.test(c))) {
        expect(NAMES[value], value).toBeTruthy();
      }
    }
  });
});
