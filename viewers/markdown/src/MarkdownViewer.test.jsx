import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMarkdown, blocksOf, blockAt } from './blocks.js';
import { locateInSource } from './locate.js';
import { clearMarks, markIn } from './mark.js';
import { GROUP, MarkdownViewer } from './MarkdownViewer.jsx';

const SOURCE = [
  '# Harvest report',
  '',
  'The price of **wheat** rose in autumn.',
  '',
  '- barley stayed flat',
  '- oats fell',
  '',
  '```',
  'wheat = 3',
  '```',
  '',
  'See [the wheat page](http://example.com/wheat) and ![a field](field.png).',
  '',
  '<script>alert(1)</script>',
].join('\n');

describe('blocks', () => {
  const md = createMarkdown();

  it('splits a text into top-level blocks with their source lines', () => {
    const blocks = blocksOf(md, SOURCE);
    expect(blocks.map((b) => [b.start, b.end])).toEqual([
      [0, 1],
      [2, 3],
      [4, 7], // a loose list holds its trailing blank line
      [7, 10],
      [11, 12],
      [13, 14],
    ]);
  });

  it('finds the block of a line, or the one before it', () => {
    const blocks = blocksOf(md, SOURCE);
    expect(blockAt(blocks, 2)).toBe(1);
    expect(blockAt(blocks, 5)).toBe(2);
    expect(blockAt(blocks, 6)).toBe(2); // a blank line belongs to the block before
    expect(blockAt(blocks, 0)).toBe(0);
    expect(blockAt(blocks, 999)).toBe(5);
  });
});

describe('locateInSource', () => {
  it('finds words through the markup', () => {
    const found = locateInSource(SOURCE, { matched: 'wheat prices' });
    expect(found).toBeNull();
    const bold = locateInSource(SOURCE, { matched: 'price of wheat' });
    expect(bold.line).toBe(3);
    expect(SOURCE.slice(bold.offset, bold.end)).toBe('price of **wheat');
  });

  it('chooses the occurrence whose surroundings match', () => {
    const text = 'wheat first.\n\nLater the price of wheat rose.';
    const found = locateInSource(text, {
      before: 'the price of ',
      matched: 'wheat',
      after: ' rose',
    });
    expect(found.line).toBe(3);
    const early = locateInSource(text, { before: '', matched: 'wheat', after: ' first' });
    expect([early.line, early.column]).toEqual([1, 1]);
  });

  it('gives the column and says nothing when the words are not there', () => {
    expect(locateInSource('abc def', { matched: 'def' }).column).toBe(5);
    expect(locateInSource('abc', { matched: 'xyz' })).toBeNull();
    expect(locateInSource('abc', { matched: '  ' })).toBeNull();
  });
});

describe('markIn', () => {
  const html = (inner) => {
    const element = document.createElement('div');
    element.innerHTML = inner;
    return element;
  };

  it('marks words across the formatting that splits them, and clears again', () => {
    const el = html('<p>the price of <strong>wheat</strong> rose</p>');
    const mark = markIn(el, { matched: 'price of wheat' });
    expect(mark.textContent).toBe('price of ');
    expect([...el.querySelectorAll('mark')].map((m) => m.textContent).join('')).toBe(
      'price of wheat',
    );
    clearMarks(el);
    expect(el.querySelector('mark')).toBeNull();
    expect(el.textContent).toBe('the price of wheat rose');
  });

  it('takes the occurrence whose surroundings match', () => {
    const el = html('<p>wheat first</p><p>then the price of wheat rose</p>');
    markIn(el, { before: 'the price of ', matched: 'wheat', after: ' rose' });
    expect(el.querySelector('mark').closest('p').textContent).toContain('then');
  });

  it('is null when the words are not in what is shown', () => {
    expect(markIn(html('<p>barley</p>'), { matched: 'wheat' })).toBeNull();
  });
});

describe('MarkdownViewer', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
  });

  it('renders the text as formatted blocks', async () => {
    render(<MarkdownViewer text={SOURCE} />);
    expect(await screen.findByRole('heading', { name: 'Harvest report' })).toBeInTheDocument();
    expect(screen.getByText('wheat', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('shows raw HTML as text, links as unclickable text and pictures as their alt text', async () => {
    const { container } = render(<MarkdownViewer text={SOURCE} />);
    await screen.findByRole('heading');
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.querySelector('a')).toBeNull();
    expect(screen.getByText('the wheat page')).toHaveClass('mdv-link');
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('[a field]')).toBeInTheDocument();
  });

  it('marks the words in the block of the target line and says so', async () => {
    const onMarked = vi.fn();
    const target = {
      line: 3,
      before: 'The price of ',
      matched: 'wheat',
      after: ' rose in autumn.',
    };
    const { container } = render(
      <MarkdownViewer text={SOURCE} target={target} onMarked={onMarked} />,
    );
    await waitFor(() => expect(container.querySelector('mark')).not.toBeNull());
    expect(container.querySelector('mark').textContent).toBe('wheat');
    expect(container.querySelector('mark').closest('[data-block]').dataset.block).toBe('1');
    expect(onMarked).toHaveBeenCalledWith(true);
  });

  it('says the words are not shown when they are not in the rendered block', async () => {
    const onMarked = vi.fn();
    const target = { line: 12, matched: 'example.com/wheat' };
    render(<MarkdownViewer text={SOURCE} target={target} onMarked={onMarked} />);
    await waitFor(() => expect(onMarked).toHaveBeenCalledWith(false));
  });

  it('moves the mark when the target moves', async () => {
    const text = 'one wheat\n\ntwo wheat\n\nthree wheat';
    const { container, rerender } = render(
      <MarkdownViewer text={text} target={{ line: 1, matched: 'wheat', before: 'one ' }} />,
    );
    await waitFor(() => expect(container.querySelector('mark')).not.toBeNull());
    rerender(
      <MarkdownViewer text={text} target={{ line: 5, matched: 'wheat', before: 'three ' }} />,
    );
    await waitFor(() =>
      expect(container.querySelector('mark').closest('p').textContent).toBe('three wheat'),
    );
    expect(container.querySelectorAll('mark')).toHaveLength(1);
  });

  it('draws only the groups near the screen when the browser can tell', async () => {
    const seen = new Map();
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback) {
          this.callback = callback;
        }
        observe(element) {
          // Only the first group is on screen.
          this.callback([{ isIntersecting: element.dataset.group === '0' }]);
          seen.set(element.dataset.group, true);
        }
        disconnect() {}
      },
    );
    const text = Array.from({ length: GROUP * 4 }, (_, i) => `paragraph ${i + 1}`).join('\n\n');
    render(<MarkdownViewer text={text} />);
    expect(await screen.findByText('paragraph 1')).toBeInTheDocument();
    expect(screen.getByText(`paragraph ${GROUP}`)).toBeInTheDocument();
    expect(screen.queryByText(`paragraph ${GROUP + 1}`)).not.toBeInTheDocument();
    // A target in a far group draws that group.
    render(
      <MarkdownViewer
        label="Far"
        text={text}
        target={{ line: GROUP * 2 * 2 + 1, matched: `paragraph ${GROUP * 2 + 1}` }}
      />,
    );
    expect(await screen.findAllByText(`paragraph ${GROUP * 2 + 1}`)).not.toHaveLength(0);
    vi.unstubAllGlobals();
  });

  it('handles an empty text', async () => {
    const { container } = render(<MarkdownViewer text="" />);
    await waitFor(() => expect(container.textContent).not.toContain('Rendering'));
  });
});
