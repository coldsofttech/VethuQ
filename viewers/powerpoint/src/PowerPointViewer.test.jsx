import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PowerPointViewer } from './index.js';

const line = (text, start) => ({ text, start });
// Indexed: "Review\nWheat fell\nRegion\tTonnes\nOutlook\nSay hello\nCheck"
const deck = (over = {}) => ({
  slides: [
    {
      n: 1,
      items: [
        { kind: 'title', level: 0, lines: [line('Review', 0)] },
        { kind: 'list', level: 0, lines: [line('Wheat fell', 7)] },
        { kind: 'row', level: 0, lines: [line('Region\tTonnes', 18)] },
        { kind: 'note', level: 0, lines: [line('Say hello', 40)] },
      ],
    },
    {
      n: 2,
      items: [
        { kind: 'title', level: 0, lines: [line('Outlook', 31)] },
        { kind: 'subtitle', level: 0, lines: [line('Next', 50)] },
      ],
    },
  ],
  first: 0,
  total: 2,
  outline: [
    { n: 1, title: 'Review' },
    { n: 2, title: 'Outlook' },
  ],
  notes: [{ text: 'Check', start: 60 }],
  ...over,
});

describe('PowerPointViewer', () => {
  it('shows an outline and each slide with its title, list, table and notes', () => {
    const { container } = render(<PowerPointViewer deck={deck()} />);
    expect(screen.getAllByRole('button', { name: /Review|Outlook/ })).toHaveLength(2);
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Review',
      'Outlook',
    ]);
    expect(container.querySelectorAll('li')).toHaveLength(1);
    expect([...container.querySelectorAll('td')].map((t) => t.textContent)).toEqual([
      'Region',
      'Tonnes',
    ]);
    expect(screen.getByLabelText('Speaker notes').textContent).toContain('Say hello');
    expect(screen.getByText('Check')).toBeInTheDocument();
  });

  it('outlines the slide of the match, marks it and says where', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <PowerPointViewer deck={deck()} match={{ start: 7, end: 12 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('Wheat');
    expect(screen.getByLabelText('Slide 1').getAttribute('aria-current')).toBe('true');
    expect(screen.getByLabelText('Slide 2').getAttribute('aria-current')).toBeNull();
    expect(onLocated).toHaveBeenLastCalledWith('slide 1');
  });

  it('marks a match in a table cell, in the other text, or nowhere', () => {
    const onLocated = vi.fn();
    const cell = render(<PowerPointViewer deck={deck()} match={{ start: 25, end: 31 }} />);
    expect(cell.container.querySelector('td mark').textContent).toBe('Tonnes');
    cell.unmount();
    render(<PowerPointViewer deck={deck()} match={{ start: 60, end: 65 }} onLocated={onLocated} />);
    expect(onLocated).toHaveBeenLastCalledWith('note');
    const none = vi.fn();
    render(<PowerPointViewer deck={deck()} match={{ start: 900, end: 905 }} onLocated={none} />);
    expect(none).toHaveBeenLastCalledWith(null);
  });

  it('goes to a slide from the outline, asking for it when it is not shown', () => {
    const onNavigate = vi.fn();
    const windowed = deck({
      first: 10,
      total: 100,
      outline: Array.from({ length: 100 }, (_, i) => ({ n: i + 1, title: `Slide ${i + 1}` })),
      slides: [{ n: 11, items: [{ kind: 'title', level: 0, lines: [line('Eleven', 0)] }] }],
    });
    render(<PowerPointViewer deck={windowed} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole('button', { name: '50Slide 50' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ first: 49 });
    fireEvent.click(screen.getByRole('button', { name: '10 earlier slides: show them' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ first: 9 });
    fireEvent.click(screen.getByRole('button', { name: '89 later slides: show them' }));
    expect(onNavigate).toHaveBeenLastCalledWith({ first: 11 });
  });

  it('says when there is no text', () => {
    render(<PowerPointViewer deck={{ slides: [], first: 0, total: 0, outline: [] }} />);
    expect(screen.getByText('This presentation has no text.')).toBeInTheDocument();
  });
});
