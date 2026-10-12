import {
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ChevronDown20Regular,
  ChevronUp20Regular,
  Dismiss20Regular,
  ZoomIn20Regular,
  ZoomOut20Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ToolButton } from '../../components/ToolButton.jsx';
import { PdfPage } from './PdfPage.jsx';
import { documentOptions, loadPdfjs } from './pdfjs.js';

const useStyles = makeStyles({
  panel: {
    display: 'flex',
    flexDirection: 'column',
    minHeight: 0,
    height: '100%',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    overflow: 'hidden',
  },
  head: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  name: {
    flexGrow: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  muted: { color: tokens.colorNeutralForeground3, whiteSpace: 'nowrap' },
  body: {
    flexGrow: 1,
    minHeight: 0,
    overflow: 'auto',
    padding: tokens.spacingVerticalS,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
  },
  centered: { margin: 'auto' },
});

const ZOOM_STEP = 1.25;
const FIT_PADDING = 24;

/**
 * A PDF of the results, shown beside them with pdf.js. It opens on the page of the chosen match,
 * marks the match's words, scrolls them into view, and steps to the file's other matches.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function PdfPreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const path = match.file_path;
  const body = useRef(null);
  const [doc, setDoc] = useState({ path: null, pdf: null, first: null, error: null });
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const [drawn, setDrawn] = useState({ scale: 0, sizes: {} });
  const [found, setFound] = useState({ key: null, marked: null, element: null });
  const key = `${path}:${match.page_number}:${match.start}`;
  // What belongs to another file or match than the one shown is not used.
  const current = doc.path === path ? doc : { pdf: null, first: null, error: null };
  const { pdf, first, error: failure } = current;

  useEffect(() => {
    let cancelled = false;
    let task = null;
    loadPdfjs()
      .then(async (lib) => {
        task = lib.getDocument(documentOptions(path));
        const opened = await task.promise;
        const page = await opened.getPage(1);
        const view = page.getViewport({ scale: 1 });
        return {
          path,
          pdf: opened,
          first: { width: view.width, height: view.height },
          error: null,
        };
      })
      .then(
        (next) => !cancelled && setDoc(next),
        (error) => !cancelled && setDoc({ path, pdf: null, first: null, error }),
      );
    return () => {
      cancelled = true;
      task?.destroy();
    };
  }, [path]);

  useEffect(() => {
    const element = body.current;
    if (!element) return undefined;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // A page is as wide as the panel at a zoom of 1. What pdf.js reports for a page, once drawn,
  // replaces the first page's size for it.
  const scale = first && width ? Math.max(0.2, ((width - FIT_PADDING) / first.width) * zoom) : 0;
  const sizes = drawn.scale === scale ? drawn.sizes : {};
  const size = (number) =>
    sizes[number] ?? { width: first.width * scale, height: first.height * scale };
  const remember = useCallback(
    (number, w, h) =>
      setDrawn((d) => {
        const same = d.scale === scale ? d.sizes : {};
        if (same[number]?.width === w && same[number]?.height === h) return d;
        return { scale, sizes: { ...same, [number]: { width: w, height: h } } };
      }),
    [scale],
  );

  const onMarked = useCallback((marked, element) => setFound({ key, marked, element }), [key]);
  const marked = found.key === key ? found.marked : null;
  const mark = found.key === key ? found.element : null;

  // Land on the page of the match, then on the match itself once it is marked.
  const scrolledTo = useRef(null);
  useEffect(() => {
    const container = body.current;
    if (!container || !scale) return;
    const at = `${key}:${scale}`;
    if (scrolledTo.current === at) return;
    const page = container.querySelector(`[data-page="${match.page_number}"]`);
    if (!page) return;
    scrolledTo.current = at;
    container.scrollTop = page.offsetTop - container.offsetTop - 8;
  });

  // Bring the marked words to the middle of the panel (only the panel scrolls, not the window).
  useEffect(() => {
    const container = body.current;
    if (!mark || !container) return;
    const inside = mark.getBoundingClientRect().top - container.getBoundingClientRect().top;
    container.scrollTop += inside - container.clientHeight / 2;
  }, [mark]);

  const pages = useMemo(
    () => (pdf ? Array.from({ length: pdf.numPages }, (_, i) => i + 1) : []),
    [pdf],
  );

  return (
    <section className={styles.panel} aria-label="PDF preview">
      <div className={styles.head}>
        <Text weight="semibold" className={styles.name} title={path}>
          {match.file_name}
        </Text>
        <Text className={styles.muted}>
          Match {index + 1} of {matches.length} · page {match.page_number}
          {pdf ? ` of ${pdf.numPages}` : ''}
        </Text>
        <ToolButton
          label="Previous match"
          icon={<ChevronUp20Regular />}
          appearance="subtle"
          disabled={index === 0}
          onClick={() => onIndex(index - 1)}
        />
        <ToolButton
          label="Next match"
          icon={<ChevronDown20Regular />}
          appearance="subtle"
          disabled={index >= matches.length - 1}
          onClick={() => onIndex(index + 1)}
        />
        <ToolButton
          label="Zoom out"
          icon={<ZoomOut20Regular />}
          appearance="subtle"
          disabled={zoom <= 0.5}
          onClick={() => setZoom((z) => z / ZOOM_STEP)}
        />
        <ToolButton
          label="Zoom in"
          icon={<ZoomIn20Regular />}
          appearance="subtle"
          disabled={zoom >= 4}
          onClick={() => setZoom((z) => z * ZOOM_STEP)}
        />
        <ToolButton
          label="Close preview"
          icon={<Dismiss20Regular />}
          appearance="subtle"
          onClick={onClose}
        />
      </div>
      {marked === false && (
        <MessageBar intent="info">
          <MessageBarBody>
            The words are not in this page&apos;s text (it may have been read by OCR), so only the
            page is shown.
          </MessageBarBody>
        </MessageBar>
      )}
      <div ref={body} className={styles.body}>
        {failure && (
          <MessageBar intent="error">
            <MessageBarBody>The PDF could not be shown: {failure.message}</MessageBarBody>
          </MessageBar>
        )}
        {!pdf && !failure && <Spinner className={styles.centered} size="small" label="Opening" />}
        {pdf &&
          first &&
          scale > 0 &&
          pages.map((number) => (
            <PdfPage
              key={number}
              pdf={pdf}
              number={number}
              scale={scale}
              size={size(number)}
              target={number === match.page_number}
              match={number === match.page_number ? match : null}
              onSize={remember}
              onMarked={number === match.page_number ? onMarked : undefined}
            />
          ))}
      </div>
    </section>
  );
}
