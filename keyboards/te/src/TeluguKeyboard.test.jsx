import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TeluguKeyboard } from './TeluguKeyboard.jsx';

const setup = () => {
  const onKey = vi.fn();
  render(<TeluguKeyboard onKey={onKey} />);
  return { typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('TeluguKeyboard', () => {
  it('is a labelled group in Telugu', () => {
    setup();
    expect(screen.getByRole('group', { name: 'Telugu on-screen keyboard' })).toHaveAttribute(
      'lang',
      'te',
    );
  });

  it('types a consonant with its vowel sign', async () => {
    const { typed } = setup();
    await press('క');
    await press('aa sign');
    expect(typed()).toEqual(['క', 'ా']);
  });

  it('types the vowel on the same key with shift, for one key', async () => {
    const { typed } = setup();
    await press('Shift');
    await press('ఆ'); // the aa sign's key, shifted
    await press('aa sign');
    expect(typed()).toEqual(['ఆ', 'ా']);
  });

  it('shows a sign on a dotted circle', () => {
    setup();
    expect(screen.getByRole('button', { name: 'virama' })).toHaveTextContent('◌్');
  });

  it('types Telugu digits, ASCII digits with shift, and has the symbols layer with backspace', async () => {
    const { typed } = setup();
    await press('౫');
    await press('Shift');
    await press('5');
    await press('Numbers and symbols');
    await press('7');
    await press('Backspace');
    await press('Letters');
    expect(typed()).toEqual(['౫', '5', '7', 'backspace']);
    expect(screen.getByRole('button', { name: 'Hide keyboard' })).toBeInTheDocument();
  });
});
