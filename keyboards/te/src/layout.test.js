import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const keysOf = (layer) => LAYERS[layer].flat().filter((key) => key.type === 'text');
const typable = (layer) => keysOf(layer).flatMap((key) => [key.value, key.shift].filter(Boolean));

const VOWELS = 'అఆఇఈఉఊఋౠఎఏఐఒఓఔ';
const CONSONANTS = 'కఖగఘఙచఛజఝఞటఠడఢణతథదధనపఫబభమయరఱలళవశషసహ';
const SIGNS = 'ాిీుూృౄెేైొోౌ్ంఃఁఽ';

describe('the Telugu layout', () => {
  it('reaches every vowel, consonant and sign, each on one key', () => {
    const all = typable('letters');
    for (const letter of [...VOWELS, ...CONSONANTS, ...SIGNS]) {
      expect(
        all.filter((c) => c === letter),
        letter,
      ).toHaveLength(1);
    }
  });

  it('has the ASCII digits on the letters layer and the Telugu digits on the symbols layer', () => {
    expect(
      typable('letters')
        .filter((c) => /\d/.test(c))
        .join(''),
    ).toBe('1234567890');
    expect(typable('symbols').join('')).toContain('౦౧౨౩౪౫౬౭౮౯');
  });

  it('shifts a key to a different Telugu character, and only letters have a shift', () => {
    for (const key of keysOf('letters')) {
      if (key.shift) {
        expect(key.shift).not.toBe(key.value);
        expect(/\p{Script=Telugu}/u.test(key.value) && /\p{Script=Telugu}/u.test(key.shift)).toBe(
          true,
        );
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
