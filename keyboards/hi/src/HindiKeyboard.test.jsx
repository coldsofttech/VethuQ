import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { HindiKeyboard } from './HindiKeyboard.jsx';

const setup = () => {
  const onKey = vi.fn();
  render(<HindiKeyboard onKey={onKey} />);
  return { typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('HindiKeyboard', () => {
  it('is a labelled group in Hindi', () => {
    setup();
    expect(screen.getByRole('group', { name: 'Hindi on-screen keyboard' })).toHaveAttribute(
      'lang',
      'hi',
    );
  });

  it('types a consonant with its vowel sign, and the vowel with shift', async () => {
    const { typed } = setup();
    await press('क');
    await press('aa sign');
    await press('Shift');
    await press('आ');
    expect(typed()).toEqual(['क', 'ा', 'आ']);
  });

  it('types the danda by the full stop, and shows a sign on a dotted circle', async () => {
    const { typed } = setup();
    await press('danda');
    expect(typed()).toEqual(['।']);
    expect(screen.getByRole('button', { name: 'halant' })).toHaveTextContent('◌्');
  });

  it('types Devanagari digits, ASCII digits with shift, and has the symbols layer', async () => {
    const { typed } = setup();
    await press('५');
    await press('Shift');
    await press('5');
    await press('Numbers and symbols');
    await press('7');
    await press('Letters');
    expect(typed()).toEqual(['५', '5', '7']);
  });
});
