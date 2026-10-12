import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useEffect, useRef, useState } from 'react';
import { locateMatch } from './locate.js';
import { loadPdfjs } from './pdfjs.js';

const useStyles = makeStyles({
  page: {
    position: 'relative',
    margin: '0 auto',
    backgroundColor: 'white',
    boxShadow: tokens.shadow4,
    flexShrink: 0,
  },
  canvas: { display: 'block' },
  text: {
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
    lineHeight: 1,
    '& span': {
      position: 'absolute',
      whiteSpace: 'pre',
      color: 'transparent',
      transformOrigin: '0 0',
    },
  },
  hit: {
    backgroundColor: 'rgba(255, 196, 0, 0.45)',
    borderRadius: '2px',
    outline: '1px solid rgba(214, 140, 0, 0.8)',
  },
});

/**
 * One page of the document: a canvas for the picture and a layer of transparent text over it (for
 * selecting, and for marking the match). It draws only while it is on screen or is the target page.
 */
export function PdfPage({ pdf, number, scale, size, target, match, onSize, onMarked }) {
  const styles = useStyles();
  const frame = useRef(null);
  const canvas = useRef(null);
  const layer = useRef(null);
  const [near, setNear] = useState(false);
  const [error, setError] = useState(false);
  const draw = near || target;

  useEffect(() => {
    const element = frame.current;
    if (!element || typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return undefined;
    }
    const observer = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), {
      rootMargin: '600px 0px',
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!draw) return undefined;
    let cancelled = false;
    let task = null;
    let text = null;
    (async () => {
      try {
        const page = await pdf.getPage(number);
        if (cancelled) return;
        const viewport = page.getViewport({ scale });
        onSize?.(number, viewport.width, viewport.height);
        const ratio = window.devicePixelRatio || 1;
        const el = canvas.current;
        el.width = Math.floor(viewport.width * ratio);
        el.height = Math.floor(viewport.height * ratio);
        el.style.width = `${Math.floor(viewport.width)}px`;
        el.style.height = `${Math.floor(viewport.height)}px`;
        task = page.render({
          canvas: el,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
        });
        const lib = await loadPdfjs();
        const container = layer.current;
        container.replaceChildren();
        container.style.setProperty('--scale-factor', String(scale));
        container.style.setProperty('--total-scale-factor', String(scale));
        text = new lib.TextLayer({
          textContentSource: page.streamTextContent(),
          container,
          viewport,
        });
        await Promise.all([task.promise, text.render()]);
        if (cancelled) return;
        if (target && match) {
          const found = locateMatch(text.textContentItemsStr, match);
          found.forEach((i) => text.textDivs[i]?.classList.add(...styles.hit.split(' ')));
          onMarked?.(found.length > 0, found.length > 0 ? text.textDivs[found[0]] : null);
        } else {
          onMarked?.(null, null);
        }
      } catch (failure) {
        console.warn('PDF page', number, failure);
        if (!cancelled && failure?.name !== 'RenderingCancelledException') setError(true);
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel?.();
      text?.cancel?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw, pdf, number, scale, target, match]);

  return (
    <div
      ref={frame}
      className={styles.page}
      style={{ width: size.width, height: size.height }}
      role="group"
      aria-label={`Page ${number}`}
      data-page={number}
    >
      {draw && <canvas ref={canvas} className={styles.canvas} />}
      <div ref={layer} className={mergeClasses(styles.text, 'pdf-text-layer')} />
      {error && <span role="alert">This page could not be drawn.</span>}
    </div>
  );
}
