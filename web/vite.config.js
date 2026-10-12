import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The production build is served by the Flask API from web/dist. There is no dev server: during
// development run `npm run dev` (rebuilds on change) next to `vethuq-desktop --no-window`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    restoreMocks: true,
  },
});
