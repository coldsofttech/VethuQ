import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CHUNK, TextViewer } from './TextViewer.jsx';

const lines = (start, count, total) =>
  Array.from({ length: Math.min(count, total - start) }, (_, i) => `line ${start + i + 1}`);

const source = (total) => vi.fn(async (start, count) => lines(start, count, total));

beforeEach(() => {
  // jsdom has no layout: the view is 400 pixels tall.
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
});
afterEach(() => vi.restoreAllMocks());

describe('TextViewer', () => {
  it('shows only the lines in view and asks for just the first chunk of a huge text', async () => {
    const loadLines = source(2_000_000);
    render(<TextViewer total={2_000_000} loadLines={loadLines} />);
    expect(await screen.findByText('line 1')).toBeInTheDocument();
    expect(screen.getByText('line 30')).toBeInTheDocument();
    expect(screen.queryByText('line 5000')).not.toBeInTheDocument();
    expect(loadLines).toHaveBeenCalledTimes(1);
    expect(loadLines).toHaveBeenCalledWith(0, CHUNK);
    expect(screen.getAllByRole('row').length).toBeLessThan(80);
    // The scrollbar is the size of the whole text.
    expect(screen.getByRole('table').firstElementChild.style.height).toBe('40000000px');
  });

  it('numbers the lines from 1', async () => {
    render(<TextViewer total={5} loadLines={source(5)} />);
    const row = (await screen.findByText('line 3')).closest('[role="row"]');
    expect(row.dataset.line).toBe('3');
    expect(row.textContent.startsWith('3')).toBe(true);
  });

  it('scrolls to the target line, marks the words on it and asks for that part of the text', async () => {
    const loadLines = source(100_000);
    render(
      <TextViewer
        total={100_000}
        loadLines={loadLines}
        target={{ line: 1000, column: 6, length: 4 }}
      />,
    );
    const mark = await screen.findByText((_, el) => el?.tagName === 'MARK');
    // "line 1000": the column is the 6th character, 4 long.
    expect(mark.textContent).toBe('1000');
    expect(screen.getByRole('table').scrollTop).toBe(999 * 20 - (400 - 20) / 2);
    expect(loadLines).toHaveBeenCalledWith(800, CHUNK);
    expect(loadLines).not.toHaveBeenCalledWith(0, CHUNK);
  });

  it('scrolls again when the target moves', async () => {
    const loadLines = source(100_000);
    const { rerender } = render(
      <TextViewer total={100_000} loadLines={loadLines} target={{ line: 100 }} />,
    );
    await screen.findByText('line 100');
    rerender(<TextViewer total={100_000} loadLines={loadLines} target={{ line: 5000 }} />);
    await screen.findByText('line 5000');
    expect(screen.getByRole('table').scrollTop).toBe(4999 * 20 - 190);
  });

  it('marks nothing without a column, and clips a mark to the line', async () => {
    const { rerender } = render(
      <TextViewer total={10} loadLines={source(10)} target={{ line: 2 }} />,
    );
    await screen.findByText('line 2');
    expect(document.querySelector('mark')).toBeNull();
    rerender(
      <TextViewer total={10} loadLines={source(10)} target={{ line: 2, column: 6, length: 50 }} />,
    );
    await waitFor(() => expect(document.querySelector('mark')?.textContent).toBe('2'));
  });

  it('starts again for another text', async () => {
    const first = source(10);
    const { rerender } = render(<TextViewer total={10} loadLines={first} />);
    await screen.findByText('line 1');
    const second = vi.fn(async (start, count) =>
      lines(start, count, 10).map((l) => l.replace('line', 'other')),
    );
    rerender(<TextViewer total={10} loadLines={second} />);
    expect(await screen.findByText('other 1')).toBeInTheDocument();
    expect(screen.queryByText('line 1')).not.toBeInTheDocument();
  });

  it('says so when the lines cannot be loaded', async () => {
    const loadLines = vi.fn(async () => {
      throw new Error('gone');
    });
    render(<TextViewer total={10} loadLines={loadLines} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded: gone');
  });

  it('copes with an empty text', () => {
    const loadLines = source(0);
    render(<TextViewer total={0} loadLines={loadLines} />);
    expect(loadLines).not.toHaveBeenCalled();
    expect(screen.queryAllByRole('row')).toHaveLength(0);
  });

  it("colours lines with `tokens` in the theme's colours and keeps the mark inside them", async () => {
    const tokens = (text) => [
      ['property', text.slice(0, 4)],
      ['value', text.slice(4)],
    ];
    const theme = {
      editor: {
        background: '#111111',
        foreground: '#eeeeee',
        gutterForeground: '#888888',
        gutterBackground: '#111111',
        gutterBorder: 'transparent',
        currentLine: '#222222',
        hitBackground: 'rgba(1, 2, 3, 0.4)',
        hitOutline: 'rgba(4, 5, 6, 0.4)',
      },
      tokens: { property: '#9cdcfe', value: '#ce9178' },
    };
    render(
      <TextViewer
        total={3}
        loadLines={source(3)}
        tokens={tokens}
        theme={theme}
        target={{ line: 2, column: 3, length: 4 }}
      />,
    );
    await waitFor(() => expect(document.querySelector('[data-line="1"]')).not.toBeNull());
    expect(screen.getByRole('table')).toHaveStyle({ background: '#111111' });
    const row = document.querySelector('[data-line="2"]');
    const parts = [...row.querySelectorAll('span span, mark')].map((n) => [
      n.textContent,
      n.style.color,
      n.tagName,
    ]);
    // "line 2" is cut at the mark "ne 2" (characters 3-6), and the mark keeps its token's colour.
    expect(parts).toEqual([
      ['li', 'rgb(156, 220, 254)', 'SPAN'],
      ['ne', 'rgb(156, 220, 254)', 'MARK'],
      [' 2', 'rgb(206, 145, 120)', 'MARK'],
    ]);
    expect(row.querySelector('mark').style.background).toContain('rgba(1, 2, 3');
    expect(row.style.background).toContain('rgb(34, 34, 34)');
  });
});
