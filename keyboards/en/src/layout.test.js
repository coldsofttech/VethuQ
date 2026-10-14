import { describe, expect, it } from 'vitest';
import { LAYERS, NAMES } from './layout.js';

const texts = (layer) =>
  LAYERS[layer]
    .flat()
    .filter((key) => key.type === 'text')
    .map((key) => key.value);

describe('the English layout', () => {
  it('has every letter once, in QWERTY order, on the letters layer', () => {
    const letters = texts('letters').filter((c) => /[a-z]/.test(c));
    expect(letters.join('')).toBe('qwertyuiopasdfghjklzxcvbnm');
  });

  it('has the digits on both layers', () => {
    for (const layer of ['letters', 'symbols']) {
      expect(
        texts(layer)
          .filter((c) => /\d/.test(c))
          .join(''),
      ).toBe('1234567890');
    }
  });

  it('has space, enter, backspace and hide on both layers, and a way to the other layer', () => {
    for (const layer of ['letters', 'symbols']) {
      const types = LAYERS[layer].flat().map((key) => key.type);
      for (const type of ['space', 'enter', 'backspace', 'close', 'layer']) {
        expect(types).toContain(type);
      }
    }
    expect(LAYERS.letters.flat().find((k) => k.type === 'layer').to).toBe('symbols');
    expect(LAYERS.symbols.flat().find((k) => k.type === 'layer').to).toBe('letters');
  });

  it('does not repeat a character on a layer, apart from the keys both layers share', () => {
    for (const layer of ['letters', 'symbols']) {
      const all = texts(layer);
      expect(new Set(all).size).toBe(all.length);
    }
  });

  it('names every character that is not a letter or a digit', () => {
    for (const layer of ['letters', 'symbols']) {
      for (const value of texts(layer).filter((c) => /[^a-z0-9]/.test(c))) {
        expect(NAMES[value], value).toBeTruthy();
      }
    }
  });
});
