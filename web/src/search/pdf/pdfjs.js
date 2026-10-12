import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

let loading = null;

/**
 * pdf.js, loaded the first time a PDF is previewed (it is the biggest part of the interface, so it
 * stays out of the first load). Its worker is a file of this app, which the CSP allows.
 */
export function loadPdfjs() {
  loading ??= import('pdfjs-dist/legacy/build/pdf.min.mjs').then((lib) => {
    lib.GlobalWorkerOptions.workerSrc = workerUrl;
    return lib;
  });
  return loading;
}

/** What pdf.js needs to open a PDF of a source: the file route, and the data files it ships (copied to /pdfjs). */
export const documentOptions = (path) => ({
  url: `/api/files/pdf?path=${encodeURIComponent(path)}`,
  cMapUrl: '/pdfjs/cmaps/',
  cMapPacked: true,
  standardFontDataUrl: '/pdfjs/standard_fonts/',
  wasmUrl: '/pdfjs/wasm/',
  iccUrl: '/pdfjs/iccs/',
});
