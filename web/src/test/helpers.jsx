import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { BrandProvider } from '../brand/BrandProvider.jsx';
import { NotifyProvider } from '../components/Notifications.jsx';
import { CreditsProvider } from '../credits/CreditsProvider.jsx';
import { IndexingProvider } from '../indexing/IndexingProvider.jsx';
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

export const IDLE = {
  run: null,
  active: false,
  paused: false,
  stopping: false,
  finished: false,
  stalled: false,
  control: null,
  eta: null,
  current_files: [],
  workers_active: 0,
  remote_jobs_open: 0,
  queued: 0,
  runner: { mode: 'idle', service_running: false, one_off: false },
  error: null,
  service: null,
};

export const NO_CREDITS = { wallets: [], primary: null };

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
    // Routes are written without a query string; one with it wins when given.
    const full = `${init.method ?? 'GET'} ${path}`;
    const key = full in routes ? full : full.split('?')[0];
    if (key === 'GET /api/brand' && !(key in routes)) return Response.json(BRAND);
    if (key === 'GET /api/credits/summary' && !(key in routes)) return Response.json(NO_CREDITS);
    if (key === 'GET /api/index/state' && !(key in routes)) return Response.json(IDLE);
    if (!(key in routes))
      return new Response(JSON.stringify({ error: 'not found' }), { status: 404 });
    // A route can be a function of the request (parsed JSON body), or a ready-made Response.
    const body = init.body ? JSON.parse(init.body) : undefined;
    const value = typeof routes[key] === 'function' ? routes[key](body) : routes[key];
    if (value instanceof Response) return value;
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
          <NotifyProvider>
            <IndexingProvider>
              <CreditsProvider>
                <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
              </CreditsProvider>
            </IndexingProvider>
          </NotifyProvider>
        </PlatformProvider>
      </ThemeProvider>
    </BrandProvider>,
  );
}
