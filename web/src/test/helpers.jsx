import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { BrandProvider } from '../brand/BrandProvider.jsx';
import { PlatformProvider } from '../platform/PlatformProvider.jsx';
import { ThemeProvider } from '../theme/ThemeProvider.jsx';

export const BRAND = {
  name: 'VethuQ',
  tagline: 'Document intelligence and evidence infrastructure.',
  palette: {
    light: { primary: '#005FB8', 'primary-hover': '#004A91', bg: '#FAFAFA', surface: '#FFFFFF' },
    dark: { primary: '#57C8FF', 'primary-hover': '#8AD8FF', bg: '#1C1C1C', surface: '#2B2B2B' },
  },
};

export const ABOUT = { vethuq: '1.2.3', python: '3.12.0', platform: 'Windows-11', db_schema: 7 };

export const CATALOG = {
  add_ons: [
    { id: 'csv', name: 'vethuq-addon-csv', version: '0.1.0', status: 'loaded', detail: '' },
  ],
  file_types: [
    { id: 'pdf', label: 'PDF', extensions: ['.pdf'], available: true, reason: '' },
    { id: 'csv', label: 'CSV', extensions: ['.csv'], available: false, reason: 'not installed' },
  ],
  search_engines: [
    { id: 'exact', label: 'Exact', description: 'As typed.', available: true, reason: '' },
  ],
  languages: [
    { id: 'en', label: 'English', native_label: '', enabled: true, available: true, reason: '' },
  ],
  ocr_engines: [],
};

/**
 * Replaces fetch with a fake API. `routes` maps "METHOD /path" to a JSON body (or a function).
 * Returns the mock so tests can assert on the calls.
 */
export function mockApi(routes) {
  const fetchMock = vi.fn(async (path, init = {}) => {
    const key = `${init.method ?? 'GET'} ${path}`;
    if (key === 'GET /api/brand' && !(key in routes)) return Response.json(BRAND);
    if (!(key in routes))
      return new Response(JSON.stringify({ error: 'not found' }), { status: 404 });
    const value = typeof routes[key] === 'function' ? routes[key]() : routes[key];
    if (value instanceof Error) throw value; // simulates the service being unreachable
    return new Response(JSON.stringify(value), { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export function renderWithProviders(ui, { route = '/' } = {}) {
  return render(
    <BrandProvider>
      <ThemeProvider>
        <PlatformProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </PlatformProvider>
      </ThemeProvider>
    </BrandProvider>,
  );
}
