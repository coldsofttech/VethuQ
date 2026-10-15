import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EmailViewer } from './index.js';

// Indexed text: "From: Ada <ada@x.org>\nSubject: Wheat\n\nPrices fell\nagain"
const message = (over = {}) => ({
  head: [
    { kind: 'from', text: 'From: Ada <ada@x.org>', start: 0 },
    { kind: 'subject', text: 'Subject: Wheat', start: 22 },
  ],
  body: [
    { text: 'Prices fell', start: 38 },
    { text: 'again', start: 50 },
  ],
  attachments: [{ name: 'report.pdf', type: 'application/pdf', size: 2048 }],
  ...over,
});

describe('EmailViewer', () => {
  it('shows the headers without their labels in the text, the attachments and the body', () => {
    render(<EmailViewer message={message()} />);
    expect(screen.getByText('Wheat')).toBeInTheDocument();
    expect(screen.getByText('Ada <ada@x.org>')).toBeInTheDocument();
    expect(screen.getByText('report.pdf (2.0 KB)')).toBeInTheDocument();
    expect(screen.getByText(/Prices fell/)).toBeInTheDocument();
  });

  it('marks a match in the body and says so', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <EmailViewer message={message()} match={{ start: 45, end: 49 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('fell');
    expect(onLocated).toHaveBeenLastCalledWith('body');
  });

  it('marks a match in a header, offset past its label', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <EmailViewer message={message()} match={{ start: 6, end: 9 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark').textContent).toBe('Ada');
    expect(onLocated).toHaveBeenLastCalledWith('headers');
  });

  it('reports no place for a match outside the lines, and marks nothing', () => {
    const onLocated = vi.fn();
    const { container } = render(
      <EmailViewer message={message()} match={{ start: 500, end: 510 }} onLocated={onLocated} />,
    );
    expect(container.querySelector('mark')).toBeNull();
    expect(onLocated).toHaveBeenLastCalledWith(null);
  });

  it('says when there is no text or no headers', () => {
    render(<EmailViewer message={{ head: [], body: [] }} />);
    expect(screen.getByText('This message has no text.')).toBeInTheDocument();
    expect(screen.getByText('This message has no headers.')).toBeInTheDocument();
  });
});
