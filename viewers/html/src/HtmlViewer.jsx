import { clearMarks, markIn } from '@vethuq/markdown-viewer';
import { useEffect, useMemo, useRef, useState } from 'react';

// Text a reader does not see in the page, so words are not looked for in it.
const HIDDEN = 'script,style,noscript,template,title,head';
const MARK_STYLE =
  'background: rgba(255, 196, 0, 0.5); color: inherit; border-radius: 2px; outline: 1px solid rgba(214, 140, 0, 0.8);';

/**
 * A page's markup with what could reach out of the frame taken out: a refresh to another address
 * and a `<base>`. (Scripts and the network are shut off by the frame's sandbox and policy.)
 *
 * @param {string} html
 * @returns {string}
 */
export function prepare(html) {
  return html
    .replace(/<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*>/gi, '')
    .replace(/<base\b[^>]*>/gi, '');
}

/**
 * A web page as a browser shows it, in a sandboxed frame, scrolled to and marking some words.
 *
 * @param {object} props
 * @param {string} props.html The page's markup.
 * @param {{before?: string, matched: string, after?: string}} [props.target] Words to land on.
 * @param {(found: boolean | null) => void} [props.onMarked] Whether the words were in what the
 *   page shows (null: there is no target).
 * @param {string} [props.label]
 */
export function HtmlViewer({ html, target, onMarked, label = 'Web page' }) {
  const frame = useRef(null);
  const [loaded, setLoaded] = useState(null);
  const source = useMemo(() => prepare(html), [html]);

  // A link does nothing and nothing is submitted, whatever the page says.
  const ready = () => {
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    doc.addEventListener('click', (event) => {
      if (event.target.closest?.('a, area')) event.preventDefault();
    });
    doc.addEventListener('submit', (event) => event.preventDefault());
    // Every load counts, not only the first: a frame can report a load of its empty first document
    // before the page, and the words are marked once the page itself is in.
    setLoaded((previous) => ({ source, load: (previous?.load ?? 0) + 1 }));
  };

  // Mark the words and scroll them (not the window around the frame) into view.
  useEffect(() => {
    const doc = frame.current?.contentDocument;
    const win = frame.current?.contentWindow;
    if (loaded?.source !== source || !doc?.body || !win) return;
    // The page itself, then the pages inside it (a web archive carries its saved frames in the
    // page as `srcdoc`, which is the page's own origin, so their words can be marked too).
    const documents = [
      doc,
      ...[...doc.querySelectorAll('iframe')].map((f) => f.contentDocument),
    ].filter((d) => d?.body);
    documents.forEach((d) => clearMarks(d.body));
    if (!target) {
      onMarked?.(null);
      return;
    }
    let mark = null;
    for (const d of documents) {
      mark = markIn(d.body, target, { skip: HIDDEN, style: MARK_STYLE });
      if (mark) break;
    }
    onMarked?.(mark !== null);
    if (mark) {
      // Scroll the frame the words are in, then the page to that frame.
      const owner = mark.ownerDocument.defaultView ?? win;
      const top = mark.getBoundingClientRect().top + owner.scrollY - owner.innerHeight / 3;
      owner.scrollTo(0, Math.max(0, top));
      if (owner !== win && owner.frameElement) {
        const inner = owner.frameElement.getBoundingClientRect().top + win.scrollY;
        win.scrollTo(0, Math.max(0, inner - win.innerHeight / 3));
      }
    }
  }, [loaded, source, target, onMarked]);

  return (
    <iframe
      ref={frame}
      title={label}
      sandbox="allow-same-origin"
      srcDoc={source}
      onLoad={ready}
      style={{ width: '100%', height: '100%', border: 0, background: '#fff', colorScheme: 'light' }}
    />
  );
}
