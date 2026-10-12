import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { describe as describeRun } from '../components/StatusBar.jsx';
import { IDLE, mockApi, renderWithProviders } from '../test/helpers.jsx';

const SOURCE = {
  id: 1,
  path: 'C:\\docs',
  name: 'docs',
  parent: 'C:\\',
  type: 'folder',
  status: 'completed',
  languages: null,
  added_at: '2026-01-01T10:00:00Z',
  last_scanned_at: null,
  removed_at: null,
  active: true,
  files_total: 3,
  files_processed: 2,
  missing: false,
};

const FILES = {
  total: 3,
  all: 3,
  items: [
    {
      path: 'C:\\docs\\a.pdf',
      relative_path: 'a.pdf',
      name: 'a.pdf',
      size_bytes: 2048,
      modified_at: '2026-01-01T10:00:00Z',
      status: 'indexed',
      file_type: 'pdf',
      protected: false,
    },
    {
      path: 'C:\\docs\\b.pdf',
      relative_path: 'b.pdf',
      name: 'b.pdf',
      size_bytes: 10,
      modified_at: '2026-01-01T10:00:00Z',
      status: 'unsupported',
      file_type: 'pdf',
      protected: true,
      error: 'Password needed',
    },
    {
      path: 'C:\\docs\\c.xyz',
      relative_path: 'c.xyz',
      name: 'c.xyz',
      size_bytes: 10,
      modified_at: '2026-01-01T10:00:00Z',
      status: 'unsupported',
      file_type: null,
      protected: false,
    },
  ],
  facets: { status: { indexed: 1, unsupported: 2 }, type: { pdf: 2 } },
};

const ROUTES = {
  'GET /api/sources': { sources: [SOURCE] },
  'GET /api/sources/1': SOURCE,
  'GET /api/sources/1/files': FILES,
};

describe('Sources', () => {
  it('lists the sources with their progress', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/sources' });
    expect(await screen.findByText('docs')).toBeInTheDocument();
    expect(screen.getByText('2 of 3')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('starts indexing the selected source', async () => {
    const fetchMock = mockApi({ ...ROUTES, 'POST /api/index/start': IDLE });
    renderWithProviders(<App />, { route: '/sources' });
    await userEvent.click(await screen.findByText('docs'));
    await userEvent.click((await screen.findAllByRole('button', { name: 'Index selected' }))[0]);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) => path === '/api/index/start');
      expect(JSON.parse(call[1].body)).toEqual({ mode: 'run', target: 1 });
    });
  });

  it('tells a failure to start in a toast', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/index/start': new Response(JSON.stringify({ error: 'Not enough credits.' }), {
        status: 402,
      }),
    });
    renderWithProviders(<App />, { route: '/sources' });
    await screen.findByText('docs');
    await userEvent.click(screen.getAllByRole('button', { name: 'Index' })[0]);
    expect(await screen.findByText('Not enough credits.')).toBeInTheDocument();
  });

  it('shows the type and status of each file, a lock for protected ones', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/sources/1' });
    const table = await screen.findByRole('table', { name: 'Files' });
    expect((await within(table).findAllByText('a.pdf')).length).toBeGreaterThan(0);
    expect(within(table).getByLabelText('Password protected')).toBeInTheDocument();
    expect(within(table).getByLabelText('Unsupported format')).toBeInTheDocument();
    expect(within(table).getByText('indexed')).toBeInTheDocument();
    expect(within(table).getAllByText('unsupported').length).toBeGreaterThan(0);
  });
});

describe('Status bar', () => {
  const run = {
    id: 1,
    target: 'C:\\docs',
    mode: 'run',
    status: 'running',
    files_total: 10,
    files_processed: 4,
    files_failed: 1,
  };

  it('says nothing when idle', () => {
    expect(describeRun(IDLE)).toBeNull();
  });

  it('describes a run in progress', () => {
    const shown = describeRun({ ...IDLE, run, active: true, eta: { seconds: 120 } });
    expect(shown.text).toContain('docs');
    expect(shown.text).toContain('4/10 files');
    expect(shown.text).toContain('1 failed');
    expect(shown.text).toContain('2 min');
    expect(shown.progress).toBeCloseTo(0.4);
  });

  it('shows the strip and asks before stopping', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/index/state': {
        ...IDLE,
        run,
        active: true,
        runner: { ...IDLE.runner, mode: 'one-off' },
      },
      'POST /api/index/stop': IDLE,
    });
    renderWithProviders(<App />, { route: '/' });
    await userEvent.click(await screen.findByRole('button', { name: 'Stop' }));
    expect(await screen.findByText('Stop indexing?')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/index/stop')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Stop indexing' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path === '/api/index/stop')).toBe(true),
    );
  });
});

describe('Indexing', () => {
  it('has its four tabs and lists the history', async () => {
    mockApi({
      'GET /api/index/history': {
        runs: [
          {
            id: 7,
            target: 'C:\\docs',
            status: 'completed',
            files_total: 3,
            files_processed: 3,
            files_failed: 0,
            started_at: '2026-01-01T10:00:00Z',
            completed_at: null,
          },
        ],
      },
    });
    renderWithProviders(<App />, { route: '/indexing/history' });
    expect(await screen.findByRole('table', { name: 'History' })).toBeInTheDocument();
    for (const name of ['Activity', 'History', 'Remote jobs', 'Queue']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
  });

  it('refreshes from its toolbar', async () => {
    const fetchMock = mockApi({ 'POST /api/index/refresh': IDLE });
    renderWithProviders(<App />, { route: '/indexing' });
    await userEvent.click(await screen.findByRole('button', { name: 'Refresh' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path === '/api/index/refresh')).toBe(true),
    );
  });
});
