import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { FrenchKeyboard } from './FrenchKeyboard.jsx';

const setup = () => {
  const onKey = vi.fn();
  render(<FrenchKeyboard onKey={onKey} />);
  return { typed: () => onKey.mock.calls.map(([key]) => key.value ?? key.type) };
};
const press = (name) => userEvent.click(screen.getByRole('button', { name }));

describe('FrenchKeyboard', () => {
  it('is a labelled group in French', () => {
    setup();
    expect(screen.getByRole('group', { name: 'French on-screen keyboard' })).toHaveAttribute(
      'lang',
      'fr',
    );
  });

  it('types the accented letters on the first layer, and capitals with shift', async () => {
    const { typed } = setup();
    await press('é');
    await press('ç');
    await press('Shift');
    await press('À');
    expect(typed()).toEqual(['é', 'ç', 'À']);
  });

  it('types the circumflex, diaeresis and ligature letters and the quotation marks on the accents layer', async () => {
    const { typed } = setup();
    await press('Accented letters');
    await press('â');
    await press('œ');
    await press('opening guillemet');
    await press('Shift');
    await press('Ö');
    await press('Letters');
    await press('a');
    expect(typed()).toEqual(['â', 'œ', '«', 'Ö', 'a']);
  });

  it('has the symbols layer', async () => {
    const { typed } = setup();
    await press('Numbers and symbols');
    await press('at sign');
    expect(typed()).toEqual(['@']);
  });
});
