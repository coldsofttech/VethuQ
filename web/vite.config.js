import react from '@vitejs/plugin-react';
import { cpSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// The data files pdf.js loads at run time (fonts, character maps, image decoders) are served by
// this app too, from /pdfjs, so the PDF preview needs no outside host.
const pdfjsData = () => ({
  name: 'pdfjs-data',
  apply: 'build',
  closeBundle() {
    const from = (name) =>
      fileURLToPath(new URL(`./node_modules/pdfjs-dist/${name}`, import.meta.url));
    const to = (name) => fileURLToPath(new URL(`./dist/pdfjs/${name}`, import.meta.url));
    for (const name of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
      cpSync(from(name), to(name), { recursive: true });
    }
  },
});

// The production build is served by the Flask API from web/dist. There is no dev server: during
// development run `npm run dev` (rebuilds on change) next to `vethuq-desktop --no-window`.
export default defineConfig({
  plugins: [react(), pdfjsData()],
  resolve: {
    // The viewers live outside web/ (viewers/*), which has no node_modules of its own: have what they
    // import resolved from here, and once.
    dedupe: [
      'react',
      'react-dom',
      'markdown-it',
      '@vethuq/markdown-viewer',
      '@testing-library/react',
      '@testing-library/dom',
      '@testing-library/user-event',
    ],
  },
  server: { fs: { allow: ['..'] } },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    include: ['src/**/*.test.{js,jsx}', '../viewers/**/*.test.{js,jsx}'],
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    restoreMocks: true,
    // Fluent dialogs and menus are slow to open in jsdom, more so when the machine is busy.
    testTimeout: 20000,
  },
});
