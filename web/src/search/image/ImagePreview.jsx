import {
  Button,
  MessageBar,
  MessageBarBody,
  Text,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowRotateClockwise20Regular,
  ArrowRotateCounterclockwise20Regular,
  ChevronLeft20Regular,
  ChevronRight20Regular,
  ScaleFit20Regular,
  ZoomIn20Regular,
  ZoomOut20Regular,
} from '@fluentui/react-icons';
import { ImageViewer, MAX_ZOOM, MIN_ZOOM } from '@vethuq/image-viewer';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api, query } from '../../api/client.js';
import { ToolButton } from '../../components/ToolButton.jsx';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  picture: { flex: '1 1 0', minHeight: 0 },
  text: {
    flex: '0 0 34%',
    minHeight: 0,
    overflow: 'auto',
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalM}`,
  },
  heading: { color: tokens.colorNeutralForeground3, display: 'block', marginBottom: '4px' },
  line: { display: 'block', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  here: { backgroundColor: tokens.colorNeutralBackground1Hover },
  hit: {
    backgroundColor: tokens.colorPaletteYellowBackground2,
    color: tokens.colorNeutralForeground1,
    borderRadius: '2px',
    padding: '0 1px',
  },
  muted: { color: tokens.colorNeutralForeground3 },
});

const ZOOM_STEP = 1.25;
const TEXT_LINES = 500;

/**
 * A picture of the results (JPEG, PNG, BMP, SVG, or a TIFF frame or GIF, WebP or HEIC page) beside them, with the text OCR read from it
 * below. The match is marked in that text and, when the engine said where it read the line, boxed
 * on the picture. Zoom, pan, turn it, and for a TIFF or an animated GIF or WebP go from frame to frame.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function ImagePreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const type = match.file_type;
  const frames = match.total_pages ?? 1;
  const matchKey = `${match.file_path}:${match.page_number}:${match.start}`;
  const [chosen, setChosen] = useState({ key: null, frame: null });
  const frame = chosen.key === matchKey ? chosen.frame : match.page_number;

  const src = `/api/files/${type}${query({ path: match.file_path, page: ['tiff', 'gif', 'webp', 'heic'].includes(type) ? frame : undefined })}`;
  const [view, setView] = useState({ src: null, zoom: 'fit', rotation: 0 });
  const { zoom, rotation } = view.src === src ? view : { zoom: 'fit', rotation: 0 };
  const change = (patch) => setView({ src, zoom, rotation, ...patch });

  // Why a picture could not be loaded: ask the same address again for the reason it answers with.
  const [problem, setProblem] = useState({ src: null, message: null });
  const explain = async () => {
    let message = 'The picture could not be shown.';
    try {
      const reply = await fetch(src, { credentials: 'same-origin' });
      if (!reply.ok) message = (await reply.json()).error ?? message;
    } catch {
      // Keep the general message.
    }
    setProblem({ src, message });
  };

  // The text OCR read from this frame.
  const [read, setRead] = useState({ key: null, lines: [], error: null });
  const readKey = `${match.document_id}:${frame}`;
  useEffect(() => {
    const controller = new AbortController();
    api.files
      .textWindow(
        { document_id: match.document_id, page: frame, start: 0, count: TEXT_LINES },
        controller.signal,
      )
      .then(
        (reply) => setRead({ key: readKey, lines: reply.lines, error: null }),
        (error) => error?.name !== 'AbortError' && setRead({ key: readKey, lines: [], error }),
      );
    return () => controller.abort();
  }, [match.document_id, frame, readKey]);
  const lines = useMemo(() => (read.key === readKey ? read.lines : []), [read, readKey]);

  const onMatchFrame = frame === match.page_number;
  const boxes = onMatchFrame && match.boxes ? match.boxes : [];
  const pieces = useMemo(() => {
    // Where each line starts in the page's text (a line break is one character).
    const starts = lines.reduce(
      (acc, text) => [...acc, acc[acc.length - 1] + text.length + 1],
      [0],
    );
    return lines.map((text, i) => {
      const start = starts[i];
      if (!onMatchFrame || match.end <= start || match.start >= start + text.length) {
        return { text, hit: null };
      }
      return {
        text,
        hit: [
          Math.max(match.start, start) - start,
          Math.min(match.end, start + text.length) - start,
        ],
      };
    });
  }, [lines, onMatchFrame, match.start, match.end]);

  const hitRow = useRef(null);
  const pane = useRef(null);
  useEffect(() => {
    const row = hitRow.current;
    const container = pane.current;
    if (!row || !container) return;
    container.scrollTop = row.offsetTop - container.clientHeight / 3;
  }, [pieces]);

  const zoomBy = (factor) => {
    const base = zoom === 'fit' ? 1 : zoom;
    change({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, base * factor)) });
  };
  const goTo = (next) => setChosen({ key: matchKey, frame: next });

  const tools = (
    <>
      {frames > 1 && (
        <>
          <ToolButton
            label="Previous frame"
            icon={<ChevronLeft20Regular />}
            appearance="subtle"
            disabled={frame <= 1}
            onClick={() => goTo(frame - 1)}
          />
          <ToolButton
            label="Next frame"
            icon={<ChevronRight20Regular />}
            appearance="subtle"
            disabled={frame >= frames}
            onClick={() => goTo(frame + 1)}
          />
        </>
      )}
      <ToolButton
        label="Zoom out"
        icon={<ZoomOut20Regular />}
        appearance="subtle"
        onClick={() => zoomBy(1 / ZOOM_STEP)}
      />
      <ToolButton
        label="Zoom in"
        icon={<ZoomIn20Regular />}
        appearance="subtle"
        onClick={() => zoomBy(ZOOM_STEP)}
      />
      <ToolButton
        label="Fit to the panel"
        icon={<ScaleFit20Regular />}
        appearance="subtle"
        onClick={() => change({ zoom: 'fit' })}
      />
      <Button size="small" appearance="subtle" onClick={() => change({ zoom: 1 })}>
        100%
      </Button>
      <ToolButton
        label="Turn left"
        icon={<ArrowRotateCounterclockwise20Regular />}
        appearance="subtle"
        onClick={() => change({ rotation: (rotation + 270) % 360 })}
      />
      <ToolButton
        label="Turn right"
        icon={<ArrowRotateClockwise20Regular />}
        appearance="subtle"
        onClick={() => change({ rotation: (rotation + 90) % 360 })}
      />
    </>
  );

  return (
    <PreviewFrame
      label="Picture preview"
      match={match}
      index={index}
      count={matches.length}
      place={frames > 1 ? `frame ${frame} of ${frames}` : 'picture'}
      onIndex={onIndex}
      onClose={onClose}
      tools={tools}
    >
      <div className={styles.body}>
        {problem.src === src && (
          <MessageBar intent="error">
            <MessageBarBody>{problem.message}</MessageBarBody>
          </MessageBar>
        )}
        <div className={styles.picture}>
          <ImageViewer
            key={src}
            src={src}
            alt={match.file_name}
            zoom={zoom}
            rotation={rotation}
            boxes={boxes}
            onZoom={(next) => change({ zoom: next })}
            onError={explain}
          />
        </div>
        <div
          className={styles.text}
          ref={pane}
          aria-label="Text read from the picture"
          role="region"
        >
          <Text size={200} className={styles.heading}>
            Text read from the picture
            {onMatchFrame && !match.boxes ? ' (where it is on the picture is not known)' : ''}
          </Text>
          {read.key === readKey && read.error && (
            <Text className={styles.muted}>The text could not be loaded: {read.error.message}</Text>
          )}
          {read.key === readKey && !read.error && lines.length === 0 && (
            <Text className={styles.muted}>No text was read from this picture.</Text>
          )}
          {pieces.map(({ text, hit }, i) => (
            <span
              key={i}
              ref={hit ? hitRow : undefined}
              className={mergeClasses(styles.line, hit && styles.here)}
            >
              {hit ? (
                <>
                  {text.slice(0, hit[0])}
                  <mark className={styles.hit}>{text.slice(hit[0], hit[1])}</mark>
                  {text.slice(hit[1])}
                </>
              ) : (
                text
              )}
            </span>
          ))}
        </div>
      </div>
    </PreviewFrame>
  );
}
