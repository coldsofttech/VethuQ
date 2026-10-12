import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { PlatformProvider } from '../platform/PlatformProvider.jsx';
import { ThemeProvider } from '../theme/ThemeProvider.jsx';

export const ABOUT = { vethuq: '1.2.3', python: '3.12.0', platform: 'Windows-11', db_schema: 7 };

/**
 * Replaces fetch with a fake API. `routes` maps "METHOD /path" to a JSON body (or a function).
 * Returns the mock so tests can assert on the calls.
 */
export function mockApi(routes) {
  const fetchMock = vi.fn(async (path, init = {}) => {
    const key = `${init.method ?? 'GET'} ${path}`;
    if (!(key in routes))
      return new Response(JSON.stringify({ error: 'not found' }), { status: 404 });
    const value = typeof routes[key] === 'function' ? routes[key]() : routes[key];
    return new Response(JSON.stringify(value), { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export function renderWithProviders(ui, { route = '/' } = {}) {
  return render(
    <ThemeProvider>
      <PlatformProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </PlatformProvider>
    </ThemeProvider>,
  );
}
