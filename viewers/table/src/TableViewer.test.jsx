import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CHUNK, TableViewer } from './TableViewer.jsx';

const data = (start, count, total, tag = 'cell') => ({
  rows: Array.from({ length: Math.max(0, Math.min(count, total - start)) }, (_, i) => [
    `${tag} ${start + i + 1}`,
    String((start + i + 1) * 2),
  ]),
  numbers: Array.from(
    { length: Math.max(0, Math.min(count, total - start)) },
    (_, i) => start + i + 2,
  ),
});

const source = (total, tag) => vi.fn(async (start, count) => data(start, count, total, tag));

beforeEach(() => {
  // jsdom has no layout: the view is 280 pixels tall.
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(280);
});
afterEach(() => vi.restoreAllMocks());

const props = (over = {}) => ({
  columns: 2,
  header: ['name', 'qty'],
  widths: [10, 6],
  total: 1000,
  loadRows: source(1000),
  ...over,
});

describe('TableViewer', () => {
  it('shows the header and only the rows in view, and asks for just the first chunk', async () => {
    const loadRows = source(1_000_000);
    render(<TableViewer {...props({ total: 1_000_000, loadRows })} />);
    expect(await screen.findByText('cell 1')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /name/ })).toBeInTheDocument();
    expect(screen.queryByText('cell 5000')).not.toBeInTheDocument();
    expect(loadRows).toHaveBeenCalledTimes(1);
    expect(loadRows).toHaveBeenCalledWith(0, CHUNK);
    // The file's own row numbers (the header is row 1) head each row.
    const row = screen.getByText('cell 1').closest('[role="row"]');
    expect(row.textContent.startsWith('2')).toBe(true);
    expect(screen.getByRole('table').lastElementChild.style.height).toBe('28000000px');
  });

  it('names a column without a header "Column N"', async () => {
    render(<TableViewer {...props({ header: null })} />);
    expect(await screen.findByRole('columnheader', { name: /Column 2/ })).toBeInTheDocument();
  });

  it('asks to sort by a column: ascending, then descending, then off', async () => {
    const onSort = vi.fn();
    const { rerender } = render(<TableViewer {...props({ onSort })} />);
    await userEvent.click(screen.getByRole('button', { name: /name/ }));
    expect(onSort).toHaveBeenLastCalledWith(0, false);
    rerender(<TableViewer {...props({ onSort, sort: { column: 0, descending: false } })} />);
    expect(screen.getByRole('columnheader', { name: /name/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    await userEvent.click(screen.getByRole('button', { name: /name/ }));
    expect(onSort).toHaveBeenLastCalledWith(0, true);
    rerender(<TableViewer {...props({ onSort, sort: { column: 0, descending: true } })} />);
    await userEvent.click(screen.getByRole('button', { name: /name/ }));
    expect(onSort).toHaveBeenLastCalledWith(null, false);
    // Another column starts ascending.
    await userEvent.click(screen.getByRole('button', { name: /qty/ }));
    expect(onSort).toHaveBeenLastCalledWith(1, false);
  });

  it('resizes a column with the arrow keys and by dragging its edge', async () => {
    render(<TableViewer {...props()} />);
    const widthOf = () => screen.getByRole('columnheader', { name: /name/ }).style.width;
    const before = parseInt(widthOf(), 10);
    const grip = screen.getByRole('separator', { name: 'Resize name' });
    grip.focus();
    await userEvent.keyboard('{ArrowRight}{ArrowRight}');
    expect(parseInt(widthOf(), 10)).toBe(before + 20);
    await userEvent.keyboard('{ArrowLeft}');
    expect(parseInt(widthOf(), 10)).toBe(before + 10);
    fireEvent.pointerDown(grip, { clientX: 100 });
    fireEvent.pointerMove(window, { clientX: 160 });
    fireEvent.pointerUp(window);
    expect(parseInt(widthOf(), 10)).toBe(before + 10 + 60);
    // Never narrower than a few characters.
    for (let i = 0; i < 100; i++) fireEvent.keyDown(grip, { key: 'ArrowLeft' });
    expect(parseInt(widthOf(), 10)).toBe(40);
    // The rows' cells follow.
    expect((await screen.findByText('cell 1')).style.width).toBe('40px');
  });

  it('scrolls to the target row and marks its cell and the text in it', async () => {
    const loadRows = source(1000);
    render(
      <TableViewer {...props({ loadRows, target: { index: 500, column: 0, text: 'ELL 501' } })} />,
    );
    const mark = await screen.findByText((_, el) => el?.tagName === 'MARK');
    expect(mark.textContent).toBe('ell 501');
    expect(screen.getByRole('table').scrollTop).toBe(500 * 28 - (280 - 28) / 2);
    expect(loadRows).toHaveBeenCalledWith(400, CHUNK);
    expect(loadRows).not.toHaveBeenCalledWith(0, CHUNK);
    // Only that cell is marked, not the same text in another column.
    const row = mark.closest('[role="row"]');
    expect(within(row).getAllByRole('cell')).toHaveLength(2);
  });

  it('marks only the row when no cell is known', async () => {
    render(<TableViewer {...props({ target: { index: 3, column: null } })} />);
    await screen.findByText('cell 4');
    expect(document.querySelector('mark')).toBeNull();
  });

  it('starts again with other rows, and says when rows cannot be loaded', async () => {
    const { rerender } = render(<TableViewer {...props()} />);
    await screen.findByText('cell 1');
    rerender(<TableViewer {...props({ loadRows: source(1000, 'other') })} />);
    expect(await screen.findByText('other 1')).toBeInTheDocument();
    expect(screen.queryByText('cell 1')).not.toBeInTheDocument();
    const broken = vi.fn(async () => {
      throw new Error('gone');
    });
    rerender(<TableViewer {...props({ loadRows: broken })} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded: gone');
  });

  it('copes with no rows', () => {
    const loadRows = source(0);
    render(<TableViewer {...props({ total: 0, loadRows })} />);
    expect(loadRows).not.toHaveBeenCalled();
    expect(screen.queryAllByRole('cell')).toHaveLength(0);
    expect(waitFor).toBeDefined();
  });
});
