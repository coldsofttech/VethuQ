import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HtmlViewer, prepare } from './HtmlViewer.jsx';

const PAGE = [
  '<html><head><title>wheat news</title><style>.w{}</style></head><body>',
  '<h1>Harvest</h1><p>The price of <b>wheat</b> rose.</p>',
  '<a href="http://example.com/oats">more</a>',
  '<script>var wheat = 1;</script>',
  '<p>wheat again</p></body></html>',
].join('\n');

const frameOf = () => screen.getByTitle('Web page');
const bodyOf = () => frameOf().contentDocument.body;

// jsdom does not load a frame's `srcdoc` itself: put the page in, as a browser would, and say so.
const loadFrame = () => {
  const frame = frameOf();
  const doc = frame.contentDocument;
  doc.open();
  doc.write(frame.getAttribute('srcdoc'));
  doc.close();
  fireEvent.load(frame);
};

describe('prepare', () => {
  it('takes out a refresh to another address and a base, and nothing else', () => {
    const page =
      '<head><base href="http://x/"><meta http-equiv="refresh" content="0;url=http://x"><meta charset="utf-8"></head><p>a</p>';
    expect(prepare(page)).toBe('<head><meta charset="utf-8"></head><p>a</p>');
    expect(prepare('<META HTTP-EQUIV=Refresh CONTENT="1">x')).toBe('x');
  });
});

describe('HtmlViewer', () => {
  it('shows the page in a frame that can run nothing', async () => {
    render(<HtmlViewer html={PAGE} />);
    const frame = frameOf();
    expect(frame.getAttribute('sandbox')).toBe('allow-same-origin');
    loadFrame();
    await waitFor(() => expect(bodyOf().textContent).toContain('Harvest'));
  });

  it('marks the words in what the page shows, and not in its script, style or title', async () => {
    const onMarked = vi.fn();
    render(
      <HtmlViewer
        html={PAGE}
        target={{ before: 'The price of ', matched: 'wheat', after: ' rose.' }}
        onMarked={onMarked}
      />,
    );
    loadFrame();
    await waitFor(() => expect(bodyOf().querySelector('mark')).not.toBeNull());
    expect(bodyOf().querySelector('mark').closest('p').textContent).toBe(
      'The price of wheat rose.',
    );
    expect(onMarked).toHaveBeenLastCalledWith(true);
    expect(frameOf().contentDocument.querySelectorAll('mark')).toHaveLength(1);
  });

  it('says the words are not shown when they are only in the script or the title', async () => {
    const onMarked = vi.fn();
    render(<HtmlViewer html={PAGE} target={{ matched: 'news' }} onMarked={onMarked} />);
    loadFrame();
    await waitFor(() => expect(onMarked).toHaveBeenCalled());
    expect(onMarked).toHaveBeenLastCalledWith(false);
    expect(bodyOf().querySelector('mark')).toBeNull();
  });

  it('moves the mark when the target moves, and clears it with no target', async () => {
    const onMarked = vi.fn();
    const { rerender } = render(
      <HtmlViewer
        html={PAGE}
        target={{ matched: 'wheat', before: 'price of ' }}
        onMarked={onMarked}
      />,
    );
    loadFrame();
    await waitFor(() => expect(bodyOf().querySelector('mark')).not.toBeNull());
    rerender(
      <HtmlViewer html={PAGE} target={{ matched: 'wheat', after: ' again' }} onMarked={onMarked} />,
    );
    await waitFor(() =>
      expect(bodyOf().querySelector('mark').closest('p').textContent).toBe('wheat again'),
    );
    expect(bodyOf().querySelectorAll('mark')).toHaveLength(1);
    rerender(<HtmlViewer html={PAGE} onMarked={onMarked} />);
    await waitFor(() => expect(bodyOf().querySelector('mark')).toBeNull());
    expect(onMarked).toHaveBeenLastCalledWith(null);
  });

  it('does nothing when a link is clicked', async () => {
    render(<HtmlViewer html={PAGE} />);
    loadFrame();
    await waitFor(() => expect(bodyOf().querySelector('a')).not.toBeNull());
    const doc = frameOf().contentDocument;
    const click = new doc.defaultView.MouseEvent('click', { bubbles: true, cancelable: true });
    bodyOf().querySelector('a').dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
  });

  it('marks words in a page saved inside the page (a web archive frame), and says it found them', async () => {
    const inner = '<html><body><p>Frame says barley today</p></body></html>';
    const outer = `<html><body><p>Main page</p><iframe srcdoc="${inner}"></iframe></body></html>`;
    const onMarked = vi.fn();
    render(
      <HtmlViewer
        html={outer}
        target={{ before: 'Frame says ', matched: 'barley', after: ' today' }}
        onMarked={onMarked}
      />,
    );
    // As a browser would: the page, then the page in its frame, then the load event.
    const frame = frameOf();
    const doc = frame.contentDocument;
    doc.open();
    doc.write(frame.getAttribute('srcdoc'));
    doc.close();
    const nested = doc.querySelector('iframe');
    nested.contentDocument.open();
    nested.contentDocument.write(nested.getAttribute('srcdoc'));
    nested.contentDocument.close();
    fireEvent.load(frame);
    await waitFor(() => expect(nested.contentDocument.querySelector('mark')).not.toBeNull());
    expect(nested.contentDocument.querySelector('mark').textContent).toBe('barley');
    expect(doc.querySelector('mark')).toBeNull(); // not in the main page
    expect(onMarked).toHaveBeenLastCalledWith(true);
  });

  it('still says the words are not in the page when no frame has them either', async () => {
    const outer =
      '<html><body><p>Main</p><iframe srcdoc="&lt;p&gt;Other&lt;/p&gt;"></iframe></body></html>';
    const onMarked = vi.fn();
    render(<HtmlViewer html={outer} target={{ matched: 'barley' }} onMarked={onMarked} />);
    loadFrame();
    await waitFor(() => expect(onMarked).toHaveBeenLastCalledWith(false));
  });
});
