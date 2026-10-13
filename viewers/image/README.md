# @vethuq/image-viewer

A read-only viewer for a picture, for VethuQ's search preview. Like the other viewers it lives outside
`web/`, knows nothing about VethuQ or its API, and has no dependency but React (a peer).

```jsx
<ImageViewer
  src="/api/files/png?path=..."
  alt="scan.png"
  zoom="fit"                      // 'fit', or a number: 1 is the picture's own size
  rotation={0}                    // 0, 90, 180 or 270 degrees clockwise
  boxes={[[0.1, 0.2, 0.5, 0.28]]} // fractions of the picture: x0, y0, x1, y1 (turn with it)
  focus={0}                       // the box to scroll into view (optional)
  onZoom={(zoom) => ...}          // the wheel changed it
  onError={() => ...}             // the picture could not be loaded
/>
```

- Scroll or drag to pan; the wheel zooms (Ctrl is not needed). `fit` shows the whole picture in the
  space there is, never larger than its own size.
- The picture is drawn by the browser, so JPEG, PNG, GIF, WebP and the like work; a TIFF needs
  converting first (VethuQ's API does it).
- Boxes are in the picture's own coordinates, so they stay on the right spot when it is zoomed or
  turned.
