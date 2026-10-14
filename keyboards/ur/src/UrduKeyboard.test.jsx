import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { UrduKeyboard } from './UrduKeyboard.jsx';

const setup = () => {
  const onKey = vi.fn();
  render(<UrduKeyboard onKey={onKey} />);
  return { typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('UrduKeyboard', () => {
  it('is a labelled group in Urdu, its keys left to right', () => {
    setup();
    const group = screen.getByRole('group', { name: 'Urdu on-screen keyboard' });
    expect(group).toHaveAttribute('lang', 'ur');
    expect(group).toHaveAttribute('dir', 'ltr');
  });

  it('types a letter, and its kin with shift', async () => {
    const { typed } = setup();
    await press('ت');
    await press('Shift');
    await press('ٹ');
    expect(typed()).toEqual(['ت', 'ٹ']);
  });

  it('types the Urdu punctuation, and shows a sign on a dotted circle', async () => {
    const { typed } = setup();
    await press('Urdu full stop');
    await press('Urdu question mark');
    expect(typed()).toEqual(['۔', '؟']);
    expect(screen.getByRole('button', { name: 'zabar' })).toHaveTextContent('◌َ');
  });

  it('types Urdu digits, ASCII digits with shift, and has the symbols layer', async () => {
    const { typed } = setup();
    await press('۵');
    await press('Shift');
    await press('5');
    await press('Numbers and symbols');
    await press('7');
    await press('Letters');
    expect(typed()).toEqual(['۵', '5', '7']);
  });
});
