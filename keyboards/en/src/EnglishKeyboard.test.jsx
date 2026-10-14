import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EnglishKeyboard } from './EnglishKeyboard.jsx';

const setup = (props) => {
  const onKey = vi.fn();
  render(<EnglishKeyboard onKey={onKey} {...props} />);
  const typed = () => onKey.mock.calls.map(([key]) => key.value ?? key.type);
  return { onKey, typed };
};

const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('EnglishKeyboard', () => {
  it('is a labelled group of keys', () => {
    setup();
    expect(screen.getByRole('group', { name: 'English on-screen keyboard' })).toBeInTheDocument();
  });

  it('reports the characters pressed, and a space as a space', async () => {
    const { typed } = setup();
    await press('h');
    await press('i');
    await press('Space');
    await press('1');
    expect(typed()).toEqual(['h', 'i', ' ', '1']);
  });

  it('reports backspace and enter', async () => {
    const { typed } = setup();
    await press('Backspace');
    await press('Enter');
    expect(typed()).toEqual(['backspace', 'enter']);
  });

  it('capitalises one letter after shift, then goes back', async () => {
    const { typed } = setup();
    await press('Shift');
    expect(screen.getByRole('button', { name: 'Shift' })).toHaveAttribute('aria-pressed', 'true');
    await press('A');
    await press('a');
    expect(typed()).toEqual(['A', 'a']);
    expect(screen.getByRole('button', { name: 'Shift' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps capitals on caps lock until shift is pressed again', async () => {
    const { typed } = setup();
    await press('Shift');
    await press('Shift');
    expect(screen.getByRole('button', { name: 'Caps lock' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await press('A');
    await press('B');
    await press('Caps lock');
    await press('c');
    expect(typed()).toEqual(['A', 'B', 'c']);
  });

  it('shows capitals on the keys while shifted', async () => {
    setup();
    await press('Shift');
    expect(screen.getByRole('button', { name: 'Q' })).toHaveTextContent('Q');
  });

  it('switches to numbers and symbols and back, which clears shift', async () => {
    const { typed } = setup();
    await press('Shift');
    await press('Numbers and symbols');
    expect(screen.queryByRole('button', { name: 'q' })).not.toBeInTheDocument();
    await press('at sign');
    await press('Letters');
    await press('q');
    expect(typed()).toEqual(['@', 'q']);
  });

  it('hides on the hide key', async () => {
    const onClose = vi.fn();
    const { onKey } = setup({ onClose });
    await press('Hide keyboard');
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onKey).not.toHaveBeenCalled();
  });

  it('keeps the focus where it was when a key is pressed with the mouse', () => {
    setup();
    const notPrevented = fireEvent.mouseDown(screen.getByRole('button', { name: 'q' }));
    expect(notPrevented).toBe(false); // default prevented: no focus change
  });
});
