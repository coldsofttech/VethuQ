import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

export const MIN_ZOOM = 0.05;
export const MAX_ZOOM = 16;
const WHEEL_STEP = 1.1;

const css = {
  root: {
    position: 'relative',
    height: '100%',
    overflow: 'auto',
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    cursor: 'grab',
    touchAction: 'none',
  },
  hit: {
    position: 'absolute',
    boxSizing: 'border-box',
    background: 'rgba(255, 196, 0, 0.3)',
    border: '2px solid rgba(214, 140, 0, 0.95)',
    borderRadius: 2,
    pointerEvents: 'none',
  },
};

const percent = (fraction) => `${Number((fraction * 100).toFixed(4))}%`;

/**
 * The scale at which a picture of `width` x `height` (turned by `rotation`) fits in a space, never
 * above its own size.
 */
export function fitScale(width, height, space, rotation = 0) {
  const turned = rotation % 180 !== 0;
  const w = turned ? height : width;
  const h = turned ? width : height;
  if (!w || !h || !space.width || !space.height) return 1;
  return Math.min(1, space.width / w, space.height / h);
}

/**
 * Where a point of the picture (fractions of its width and height, from its top-left) is on the
 * stage the picture is drawn on once it is turned `rotation` degrees clockwise (also fractions).
 */
export function toStage([x, y], rotation = 0) {
  switch (((rotation % 360) + 360) % 360) {
    case 90:
      return [1 - y, x];
    case 180:
      return [1 - x, 1 - y];
    case 270:
      return [y, 1 - x];
    default:
      return [x, y];
  }
}

/**
 * A picture the reader can zoom, pan and turn, with boxes drawn on it (they turn with it).
 *
 * @param {object} props
 * @param {string} props.src
 * @param {string} [props.alt]
 * @param {'fit' | number} [props.zoom] 'fit', or the scale (1 is the picture's own size).
 * @param {number} [props.rotation] Degrees clockwise: 0, 90, 180 or 270.
 * @param {Array<[number, number, number, number]>} [props.boxes] Fractions: x0, y0, x1, y1.
 * @param {number} [props.focus] The index of the box to bring into view.
 * @param {(zoom: number) => void} [props.onZoom] The wheel changed the zoom to this scale.
 * @param {() => void} [props.onError] The picture could not be loaded.
 */
export function ImageViewer({
  src,
  alt = '',
  zoom = 'fit',
  rotation = 0,
  boxes = [],
  focus = 0,
  onZoom,
  onError,
}) {
  const root = useRef(null);
  const drag = useRef(null);
  const [natural, setNatural] = useState(null);
  const [space, setSpace] = useState({ width: 0, height: 0 });
  const [failed, setFailed] = useState(false);

  const measure = useCallback(() => {
    const element = root.current;
    if (element) setSpace({ width: element.clientWidth, height: element.clientHeight });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = root.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  const scale = useMemo(() => {
    if (!natural) return 1;
    const wanted =
      zoom === 'fit' ? fitScale(natural.width, natural.height, space, rotation) : Number(zoom);
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, wanted));
  }, [natural, zoom, space, rotation]);

  const turned = rotation % 180 !== 0;
  const width = natural ? natural.width * scale : 0;
  const height = natural ? natural.height * scale : 0;
  const stage = { width: turned ? height : width, height: turned ? width : height };

  // Bring the focused box to the middle of the view when it is larger than the space.
  const focused = boxes[focus];
  const focusKey = focused ? `${focused.join(',')}:${rotation}:${scale}` : '';
  useEffect(() => {
    const element = root.current;
    if (!element || !focused || !natural) return;
    const [cx, cy] = toStage(
      [(focused[0] + focused[2]) / 2, (focused[1] + focused[3]) / 2],
      rotation,
    );
    element.scrollLeft = Math.max(0, cx * stage.width - element.clientWidth / 2);
    element.scrollTop = Math.max(0, cy * stage.height - element.clientHeight / 2);
    // Only when the box, the turn or the scale changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, natural]);

  const wheel = (event) => {
    if (!onZoom) return;
    event.preventDefault();
    const next = scale * (event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP);
    onZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next)));
  };
  const press = (event) => {
    const element = root.current;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      left: element.scrollLeft,
      top: element.scrollTop,
    };
    element.setPointerCapture?.(event.pointerId);
    element.style.cursor = 'grabbing';
  };
  const move = (event) => {
    const start = drag.current;
    if (!start) return;
    root.current.scrollLeft = start.left - (event.clientX - start.x);
    root.current.scrollTop = start.top - (event.clientY - start.y);
  };
  const release = () => {
    drag.current = null;
    if (root.current) root.current.style.cursor = 'grab';
  };

  return (
    <div
      ref={root}
      role="group"
      aria-label={alt || 'Picture'}
      style={css.root}
      onWheel={wheel}
      onPointerDown={press}
      onPointerMove={move}
      onPointerUp={release}
      onPointerCancel={release}
    >
      {failed && (
        <div role="alert" style={{ padding: 16 }}>
          The picture could not be shown.
        </div>
      )}
      <div
        data-stage=""
        style={{
          position: 'relative',
          width: Math.max(stage.width, space.width),
          height: Math.max(stage.height, space.height),
        }}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          onLoad={(event) => {
            setFailed(false);
            setNatural({
              width: event.currentTarget.naturalWidth,
              height: event.currentTarget.naturalHeight,
            });
          }}
          onError={() => {
            setFailed(true);
            onError?.();
          }}
          style={
            natural
              ? {
                  position: 'absolute',
                  width,
                  height,
                  left: (Math.max(stage.width, space.width) - width) / 2,
                  top: (Math.max(stage.height, space.height) - height) / 2,
                  transform: `rotate(${rotation}deg)`,
                  userSelect: 'none',
                }
              : { position: 'absolute', opacity: 0, width: 1, height: 1 }
          }
        />
        {natural && (
          <div
            data-picture=""
            style={{
              position: 'absolute',
              width,
              height,
              left: (Math.max(stage.width, space.width) - width) / 2,
              top: (Math.max(stage.height, space.height) - height) / 2,
              transform: `rotate(${rotation}deg)`,
            }}
          >
            {boxes.map(([x0, y0, x1, y1], i) => (
              <div
                key={i}
                data-box=""
                style={{
                  ...css.hit,
                  left: percent(x0),
                  top: percent(y0),
                  width: percent(x1 - x0),
                  height: percent(y1 - y0),
                  zIndex: 1,
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
