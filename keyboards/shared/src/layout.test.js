import { describe, expect, it } from 'vitest';
import { PUNCTUATION_NAMES, bottomRow, cased, keys, symbolsLayer } from './layout.js';

describe('keys', () => {
  it('makes a key per character, with its shifted character when there is one', () => {
    expect(keys('ab', 'AB')).toEqual([
      { type: 'text', value: 'a', shift: 'A' },
      { type: 'text', value: 'b', shift: 'B' },
    ]);
    expect(keys('12')).toEqual([
      { type: 'text', value: '1' },
      { type: 'text', value: '2' },
    ]);
  });

  it('keeps a character made of several code units whole', () => {
    expect(keys('😀x').map((k) => k.value)).toEqual(['😀', 'x']);
  });
});

describe('cased', () => {
  it('shifts each letter to its capital, including letters with a mark and ligatures', () => {
    expect(cased('aé')).toEqual([
      { type: 'text', value: 'a', shift: 'A' },
      { type: 'text', value: 'é', shift: 'É' },
    ]);
    expect(cased('œÿ').map((k) => k.shift)).toEqual(['Œ', 'Ÿ']);
  });
});

describe('bottomRow and symbolsLayer', () => {
  it('takes several layer keys, which come first', () => {
    const row = bottomRow([
      { type: 'layer', to: 'a', label: 'a' },
      { type: 'layer', to: 'b', label: 'b' },
    ]);
    expect(row.map((k) => k.type).slice(0, 3)).toEqual(['layer', 'layer', 'text']);
  });

  it('ends every layer with the layer key, comma, full stop, space, enter and hide', () => {
    const row = bottomRow({ type: 'layer', to: 'x', label: 'x' });
    expect(row.map((k) => k.type)).toEqual(['layer', 'text', 'text', 'space', 'enter', 'close']);
  });

  it('takes the marks between the layer key and space', () => {
    const row = bottomRow({ type: 'layer', to: 'x', label: 'x' }, ',।.');
    expect(row.filter((k) => k.type === 'text').map((k) => k.value)).toEqual([',', '।', '.']);
  });

  it('puts the language’s digits in the first row and names all its punctuation', () => {
    const layer = symbolsLayer('abcdefghij', { type: 'layer', to: 'x', label: 'x' });
    expect(layer[0].map((k) => k.value).join('')).toBe('abcdefghij');
    const symbols = layer
      .slice(1)
      .flat()
      .filter((k) => k.type === 'text' && !/[,.]/.test(k.value));
    for (const { value } of symbols) expect(PUNCTUATION_NAMES[value], value).toBeTruthy();
  });
});
