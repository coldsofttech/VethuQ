import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WordViewer } from './index.js';

// Indexed: "Report\nSummary\nWheat fell\nOne\nTwo\nRegion\nTonnes\nNorth\n12\na\tb"
const doc = (over = {}) => ({
  blocks: [
    { kind: 'title', text: 'Report', start: 0 },
    { kind: 'heading', text: 'Summary', start: 7, level: 2 },
    { kind: 'text', text: 'Wheat fell', start: 15 },
    { kind: 'list', text: 'One', start: 26, level: 0 },
    { kind: 'list', text: 'Two', start: 30, level: 1 },
    { kind: 'cell', text: 'Region', start: 34, row: 1, cell: 1 },
    { kind: 'cell', text: 'Tonnes', start: 41, row: 1, cell: 2 },
    { kind: 'cell', text: 'North', start: 48, row: 2, cell: 1 },
    { kind: 'cell', text: '12', start: 54, row: 2, cell: 2 },
    { kind: 'row', text: 'a\tb', start: 57 },
  ],
  first: 0,
  total: 10,
  ...over,
});

describe('WordViewer', () => {
  it('lays out headings, lists and tables', () => {
    const { container } = render(<WordViewer document={doc()} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Summary');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(container.querySelectorAll('tr')).toHaveLength(3);
    expect(container.querySelectorAll('tr')[0].querySelectorAll('td')).toHaveLength(2);
    expect(screen.getByText('Wheat fell')).toBeInTheDocument();
  });

  it('marks a match, outlines its block and says which', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <WordViewer document={doc()} match={{ start: 15, end: 20 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('Wheat');
    expect(container.querySelector('[aria-current="true"]').textContent).toBe('Wheat fell');
    expect(onLocated).toHaveBeenLastCalledWith(3);
  });

  it('marks a match in a table cell and in a tab-joined row', () => {
    const cell = render(<WordViewer document={doc()} match={{ start: 48, end: 53 }} />);
    expect(cell.container.querySelector('mark').textContent).toBe('North');
    cell.unmount();
    const row = render(<WordViewer document={doc()} match={{ start: 59, end: 60 }} />);
    expect(row.container.querySelector('mark').textContent).toBe('b');
  });

  it('says where a window of a long document sits, and when nothing is matched', () => {
    const onLocated = vi.fn();
    render(
      <WordViewer
        document={doc({ first: 40, total: 100 })}
        match={{ start: 15, end: 20 }}
        onLocated={onLocated}
      />,
    );
    expect(screen.getByText('40 earlier lines not shown.')).toBeInTheDocument();
    expect(screen.getByText('50 later lines not shown.')).toBeInTheDocument();
    expect(onLocated).toHaveBeenLastCalledWith(43);
  });

  it('says when there is no text', () => {
    render(<WordViewer document={{ blocks: [], first: 0, total: 0 }} />);
    expect(screen.getByText('This document has no text.')).toBeInTheDocument();
  });
});
