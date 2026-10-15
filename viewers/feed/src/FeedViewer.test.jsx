import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FeedViewer } from './index.js';

const feed = (over = {}) => ({
  format: 'rss',
  language: 'en',
  updated: 'Tue, 14 Oct 2026',
  well_formed: true,
  head: [
    { kind: 'title', text: 'Dev Blog', start: 0 },
    { kind: 'description', text: 'Notes', start: 9 },
  ],
  entries: [
    {
      lines: [
        { kind: 'title', text: 'First', start: 15 },
        { kind: 'author', text: 'Author: Ada', start: 21 },
        { kind: 'link', text: 'Link: https://example.com/1', start: 33 },
        { kind: 'text', text: 'Wheat prices fell', start: 61 },
      ],
    },
    {
      lines: [
        { kind: 'title', text: 'Second', start: 79 },
        { kind: 'link', text: 'Link: javascript:alert(1)', start: 86 },
      ],
    },
  ],
  first: 0,
  total: 2,
  file_name: 'blog.rss',
  ...over,
});

describe('FeedViewer', () => {
  it('shows the feed, its facts and each entry', () => {
    render(<FeedViewer feed={feed()} />);
    expect(screen.getByText('Dev Blog')).toBeInTheDocument();
    expect(screen.getByText('Notes')).toBeInTheDocument();
    expect(screen.getByText('rss')).toBeInTheDocument();
    expect(screen.getByText('2 entries')).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect(screen.getByText(/Author: Ada/)).toBeInTheDocument();
  });

  it('outlines the entry the match is in, marks the words and says which entry', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <FeedViewer feed={feed()} match={{ start: 61, end: 66 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('Wheat');
    const [first, second] = screen.getAllByRole('article');
    expect(first.getAttribute('aria-current')).toBe('true');
    expect(second.getAttribute('aria-current')).toBeNull();
    expect(onLocated).toHaveBeenLastCalledWith(1);
  });

  it('marks a match in a labelled line without the label', () => {
    const { container } = render(<FeedViewer feed={feed()} match={{ start: 29, end: 32 }} />);
    expect(container.querySelector('mark').textContent).toBe('Ada');
  });

  it('numbers the entry from the start of the whole feed and says null when it is in none', () => {
    const onLocated = vi.fn();
    const window = feed({ first: 40, total: 100 });
    const { rerender } = render(
      <FeedViewer feed={window} match={{ start: 79, end: 85 }} onLocated={onLocated} />,
    );
    expect(onLocated).toHaveBeenLastCalledWith(42);
    expect(screen.getByText('40 earlier entries not shown.')).toBeInTheDocument();
    expect(screen.getByText('58 later entries not shown.')).toBeInTheDocument();
    rerender(<FeedViewer feed={window} match={{ start: 9000, end: 9005 }} onLocated={onLocated} />);
    expect(onLocated).toHaveBeenLastCalledWith(null);
  });

  it('makes only a web address a link', () => {
    render(<FeedViewer feed={feed()} />);
    const link = screen.getByRole('link', { name: 'https://example.com/1' });
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(screen.queryByRole('link', { name: /javascript/ })).toBeNull();
    expect(screen.getByText(/javascript:alert\(1\)/)).toBeInTheDocument();
  });

  it('says so when the feed was not well-formed, and a single entry is not plural', () => {
    render(<FeedViewer feed={feed({ well_formed: false, total: 1 })} />);
    expect(screen.getByRole('note').textContent).toMatch(/not well-formed/);
    expect(screen.getByText('1 entry')).toBeInTheDocument();
  });
});
