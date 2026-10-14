import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Keyboard, typedValue } from './Keyboard.jsx';
import { backspaceKey, bottomRow, keys, shiftKey } from './layout.js';

// A small layout of its own, so the shared keyboard is tested without any language.
const layers = {
  main: [
    [...keys('ab', 'AB'), ...keys('ா', 'X')],
    [shiftKey, backspaceKey],
    bottomRow({ type: 'layer', to: 'other', label: 'other', name: 'Other layer' }),
  ],
  other: [keys('12'), bottomRow({ type: 'layer', to: 'main', label: 'main', name: 'Main layer' })],
};

const setup = (props) => {
  const onKey = vi.fn();
  render(<Keyboard layers={layers} onKey={onKey} label="Test keyboard" lang="xx" {...props} />);
  return { onKey, typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('typedValue', () => {
  it('is the shifted character while shifted, when the key has one', () => {
    expect(typedValue({ value: 'a', shift: 'A' }, true)).toBe('A');
    expect(typedValue({ value: 'a', shift: 'A' }, false)).toBe('a');
    expect(typedValue({ value: '1' }, true)).toBe('1');
  });
});

describe('Keyboard', () => {
  it('is a labelled group in its language, showing the first layer', () => {
    setup();
    expect(screen.getByRole('group', { name: 'Test keyboard' })).toHaveAttribute('lang', 'xx');
    expect(screen.getByRole('button', { name: 'a' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '1' })).not.toBeInTheDocument();
  });

  it('reports text, a space as a space, backspace and enter', async () => {
    const { typed } = setup();
    await press('a');
    await press('Space');
    await press('Backspace');
    await press('Enter');
    expect(typed()).toEqual(['a', ' ', 'backspace', 'enter']);
  });

  it('shifts one key, then goes back; again for caps lock; again to turn it off', async () => {
    const { typed } = setup();
    await press('Shift');
    await press('A');
    await press('a');
    await press('Shift');
    await press('Shift');
    expect(screen.getByRole('button', { name: 'Caps lock' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await press('A');
    await press('B');
    await press('Caps lock');
    await press('a');
    expect(typed()).toEqual(['A', 'a', 'A', 'B', 'a']);
  });

  it('switches layer by the name the layout gives, which clears shift', async () => {
    const { typed } = setup();
    await press('Shift');
    await press('Other layer');
    await press('1');
    await press('Main layer');
    await press('a');
    expect(typed()).toEqual(['1', 'a']);
  });

  it('shows a combining sign on a dotted circle, and names a key by its names map', () => {
    setup({ names: { 'ா': 'aa sign' } });
    expect(screen.getByRole('button', { name: 'aa sign' })).toHaveTextContent('◌ா');
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
    expect(fireEvent.mouseDown(screen.getByRole('button', { name: 'a' }))).toBe(false);
  });
});
