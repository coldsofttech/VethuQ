import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SpanishKeyboard } from './SpanishKeyboard.jsx';

const setup = () => {
  const onKey = vi.fn();
  render(<SpanishKeyboard onKey={onKey} />);
  return { typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('SpanishKeyboard', () => {
  it('is a labelled group in Spanish', () => {
    setup();
    expect(screen.getByRole('group', { name: 'Spanish on-screen keyboard' })).toHaveAttribute(
      'lang',
      'es',
    );
  });

  it('types ñ and the accented vowels, and capitals with shift', async () => {
    const { typed } = setup();
    await press('ñ');
    await press('á');
    await press('ü');
    await press('Shift');
    await press('Ñ');
    expect(typed()).toEqual(['ñ', 'á', 'ü', 'Ñ']);
  });

  it('types the inverted question and exclamation marks', async () => {
    const { typed } = setup();
    await press('inverted question mark');
    await press('inverted exclamation mark');
    expect(typed()).toEqual(['¿', '¡']);
  });

  it('has the symbols layer', async () => {
    const { typed } = setup();
    await press('Numbers and symbols');
    await press('7');
    await press('Letters');
    await press('q');
    expect(typed()).toEqual(['7', 'q']);
  });
});
