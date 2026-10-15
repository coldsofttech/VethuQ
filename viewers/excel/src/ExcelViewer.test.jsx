import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ExcelViewer, columnName } from './index.js';

// Indexed: "Prices\nRegion\tTonnes\nNorth\t12400\nNotes\nwheat"
const book = (over = {}) => ({
  sheets: [
    { name: 'Prices', name_start: 0, rows: 2, cols: 3 },
    { name: 'Notes', name_start: 34, rows: 1, cols: 2 },
  ],
  sheet: 0,
  first: 0,
  rows: [
    {
      r: 1,
      cells: [
        { c: 0, t: 'Region', n: false, s: 7 },
        { c: 2, t: 'Tonnes', n: false, s: 14 },
      ],
    },
    {
      r: 4,
      cells: [
        { c: 0, t: 'North', n: false, s: 21 },
        { c: 2, t: '12400', n: true, s: 27 },
      ],
    },
  ],
  notes: [{ text: 'A comment', start: 45 }],
  limited_columns: false,
  ...over,
});

describe('ExcelViewer', () => {
  it('names columns the way a spreadsheet does', () => {
    expect([0, 1, 25, 26, 27, 51, 52, 701, 702].map(columnName)).toEqual([
      'A',
      'B',
      'Z',
      'AA',
      'AB',
      'AZ',
      'BA',
      'ZZ',
      'AAA',
    ]);
  });

  it('shows a grid with column letters, row numbers and the cells in their columns', () => {
    const { container } = render(<ExcelViewer workbook={book()} />);
    expect([...container.querySelectorAll('thead th')].map((t) => t.textContent)).toEqual([
      '',
      'A',
      'B',
      'C',
    ]);
    expect([...container.querySelectorAll('tbody th')].map((t) => t.textContent)).toEqual([
      '1',
      '4',
    ]);
    const second = container.querySelectorAll('tbody tr')[1].querySelectorAll('td');
    expect([...second].map((t) => t.textContent)).toEqual(['North', '', '12400']);
    expect(second[2].style.textAlign).toBe('right');
    expect(screen.getByText('A comment')).toBeInTheDocument();
  });

  it('outlines and marks the cell of the match, and says where it is', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <ExcelViewer workbook={book()} match={{ start: 28, end: 30 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('24');
    expect(container.querySelector('td[aria-current="true"]').textContent).toBe('12400');
    expect(onLocated).toHaveBeenLastCalledWith('Prices!C4');
  });

  it('finds a match in a sheet name, a note, or nowhere', () => {
    const onLocated = vi.fn();
    const name = render(
      <ExcelViewer workbook={book()} match={{ start: 0, end: 3 }} onLocated={onLocated} />,
    );
    expect(onLocated).toHaveBeenLastCalledWith('Prices');
    expect(name.container.querySelector('[role="tab"] mark').textContent).toBe('Pri');
    name.unmount();
    render(<ExcelViewer workbook={book()} match={{ start: 45, end: 50 }} onLocated={onLocated} />);
    expect(onLocated).toHaveBeenLastCalledWith('note');
    const none = vi.fn();
    render(<ExcelViewer workbook={book()} match={{ start: 900, end: 905 }} onLocated={none} />);
    expect(none).toHaveBeenLastCalledWith(null);
  });

  it('switches sheet from its tab and pages through the rows', () => {
    const onNavigate = vi.fn();
    const long = book({
      first: 500,
      sheets: [
        { name: 'Prices', name_start: 0, rows: 1200, cols: 3 },
        { name: 'Notes', name_start: null, rows: 1, cols: 1 },
      ],
    });
    render(<ExcelViewer workbook={long} onNavigate={onNavigate} />);
    expect(screen.getByText(/Rows 501–502 of 1200/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next rows' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ sheet: 0, first: 502 });
    fireEvent.click(screen.getByRole('button', { name: 'Previous rows' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ sheet: 0, first: 498 });
    fireEvent.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ sheet: 1, first: null });
    expect(screen.getByRole('tab', { name: 'Prices' }).getAttribute('aria-selected')).toBe('true');
  });

  it('says when a sheet has no cells', () => {
    render(<ExcelViewer workbook={book({ rows: [], notes: [] })} />);
    expect(screen.getByText('This sheet has no cells.')).toBeInTheDocument();
  });
});
