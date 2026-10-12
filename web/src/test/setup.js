import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
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

// The first Fluent dialog or menu opened in a test file is slow in jsdom (styles are generated on
// first use), so wait longer than the 1 second default before giving up.
configure({
  asyncUtilTimeout: 10000,
  // Fluent's modal dialogs are briefly aria-hidden in jsdom while their focus trap starts (a real
  // browser, checked end to end, exposes them at once), so role queries must see through that.
  defaultHidden: true,
});
