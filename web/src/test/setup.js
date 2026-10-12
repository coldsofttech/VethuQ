import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

// jsdom has no ResizeObserver, which Fluent's MessageBar needs.
window.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
