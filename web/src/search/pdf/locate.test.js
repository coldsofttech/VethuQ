import { describe, expect, it } from 'vitest';
import { locateMatch } from './locate.js';

const match = (matched, before = '', after = '') => ({ before, matched, after });

describe('locateMatch', () => {
  it('finds the items that hold the words', () => {
    const items = ['The harvest of ', 'wheat', ' rose in autumn'];
    expect(locateMatch(items, match('wheat'))).toEqual([1]);
  });

  it('ignores spaces, line ends and case, and joins words split over items', () => {
    const items = ['Spring', ' whe', 'at ', '\n', 'Prices'];
    expect(locateMatch(items, match('Wheat'))).toEqual([1, 2]);
    expect(locateMatch(['a w', 'heat b'], match('wheat'))).toEqual([0, 1]);
    expect(locateMatch(['the', 'harvest', 'of'], match('harvest of'))).toEqual([1, 2]);
  });

  it("takes the occurrence whose surroundings are the match's own", () => {
    const items = ['wheat is key. ', 'The price of ', 'wheat', ' rose.'];
    expect(locateMatch(items, match('wheat', 'the price of ', ' rose.'))).toEqual([2]);
    expect(locateMatch(items, match('wheat', '', ' is key.'))).toEqual([0]);
  });

  it('says nothing when the words are not on the page', () => {
    expect(locateMatch(['barley only'], match('wheat'))).toEqual([]);
    expect(locateMatch([], match('wheat'))).toEqual([]);
    expect(locateMatch(['text'], match('  '))).toEqual([]);
  });
});
