import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const IDLE = { running: false, result: null, error: null, finished: false };
const TASKS = { 'db-check': IDLE, 'search-rebuild': IDLE };

const BASE = {
  'GET /api/maintenance/tasks': TASKS,
  'GET /api/db': { last: null },
  'GET /api/updates': {
    status: 'available',
    current: '1.0.0',
    latest: '1.2.0',
    minimum_supported: '0.9.0',
    distribution: 'pip',
    release_notes_url: 'https://example.com/notes',
    message: 'Version 1.2.0 is out.',
    disabled_by_environment: false,
  },
  'GET /api/search-index': { pages_indexed: 40, pages_total: 50, current: false, full_text: true },
  'GET /api/tiers': {
    tiers: [
      { id: 'local', label: 'Local', wallet: 'local', available: true, reason: '', selected: true },
      {
        id: 'github',
        label: 'GitHub',
        wallet: 'github',
        available: false,
        reason: 'no runner',
        selected: false,
      },
    ],
  },
  'GET /api/policy': {
    source: 'cache',
    status: 'current',
    detail: '',
    update_required: false,
    sequence: 7,
    kid: 'key-1',
    schema_version: 1,
    issued_at: '2026-10-01T00:00:00+00:00',
    versions: { pip: { latest: '1.2.0', minimum_supported: '0.9.0' } },
    notices: [{ id: 'n1', message: 'Scheduled maintenance.', severity: 'warning', link: null }],
    features: { github_tier: { enabled: false, min_client: '2.0', message: 'Needs 2.0' } },
    addons: { github: { enabled: false, latest: '0.2', message: 'Withdrawn' } },
  },
  'GET /api/metrics': {
    opted_in: true,
    available: true,
    last_sent_at: '2026-10-11T08:00:00+00:00',
    sent_through: '2026-10-10',
    pending_days: 1,
    bonus_active: true,
    bonus_percent: 10,
  },
  'GET /api/metrics/preview': {
    size_bytes: 2048,
    batch: {
      schema: 1,
      batch_id: 'b1',
      install_id: 'anon-123',
      client: { vethuq: '1.0.0', os: 'windows', ram_bucket: '16' },
      settings: { workers: 'auto', languages: ['en', 'ta'] },
      days: [
        {
          day: '2026-10-11',
          pages: [
            {
              file_type: 'pdf',
              phase: 'quick',
              language: 'en',
              engine: 'paddle',
              page_source: 'ocr',
              size_bucket: 'a4',
              band: 'high',
              pages: 5,
              passes: 5,
              duration_ms: 9000,
              confidence_sum: 4.5,
              credits_milli: 5000,
            },
            {
              file_type: 'txt',
              phase: '',
              language: 'en',
              engine: '',
              page_source: 'native',
              size_bucket: 'a4',
              band: '',
              pages: 7,
              passes: 0,
              duration_ms: 0,
              confidence_sum: 0,
              credits_milli: 0,
            },
          ],
          failures: [{ file_type: 'pdf', code: 'password', count: 2 }],
        },
      ],
    },
  },
  'GET /api/settings/general': { section: 'general', settings: [] },
  'GET /api/settings/system': { section: 'system', settings: [] },
  'GET /api/settings/search': { section: 'search', settings: [] },
  'GET /api/settings/tiers': { section: 'tiers', settings: [] },
};

describe('Updates', () => {
  it('shows what was found and checks on demand', async () => {
    const fetchMock = mockApi({ ...BASE, 'POST /api/updates/check': BASE['GET /api/updates'] });
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByText('1.2.0')).toBeInTheDocument();
    expect(screen.getByText('An update is available')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Release notes' })).toHaveAttribute(
      'href',
      'https://example.com/notes',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await waitFor(() =>
      expect(
        JSON.parse(fetchMock.mock.calls.find(([p]) => p === '/api/updates/check')[1].body),
      ).toEqual({ force: true }),
    );
  });
});

describe('Database check', () => {
  it('has no result yet, then runs a quick check and shows the problem list', async () => {
    let going = false;
    const fetchMock = mockApi({
      ...BASE,
      'GET /api/maintenance/tasks': () => ({
        ...TASKS,
        'db-check': going ? { running: true, result: null, error: null, finished: false } : IDLE,
      }),
      'POST /api/db/check': () => {
        going = true;
        return { running: true, result: null, error: null, finished: false };
      },
    });
    renderWithProviders(<App />, { route: '/settings/system' });
    expect(await screen.findByText('The database has not been checked yet.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Quick check' }));
    await waitFor(() =>
      expect(JSON.parse(fetchMock.mock.calls.find(([p]) => p === '/api/db/check')[1].body)).toEqual(
        { quick: true },
      ),
    );
    expect(await screen.findByText('Checking')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Full check' })).toBeDisabled();
  });

  it('shows the last result and what SQLite said', async () => {
    mockApi({
      ...BASE,
      'GET /api/db': {
        last: {
          ok: false,
          errors: ['Page 4 is damaged'],
          checked_at: '2026-10-12T10:00:00+00:00',
          quick: false,
        },
      },
    });
    renderWithProviders(<App />, { route: '/settings/system' });
    expect(await screen.findByText('Page 4 is damaged')).toBeInTheDocument();
    expect(screen.getByText(/1 problem found/)).toBeInTheDocument();
  });
});

describe('Search index', () => {
  it('shows its state and rebuilds it', async () => {
    let going = false;
    const fetchMock = mockApi({
      ...BASE,
      'GET /api/maintenance/tasks': () => ({
        ...TASKS,
        'search-rebuild': going
          ? { running: true, result: null, error: null, finished: false }
          : IDLE,
      }),
      'POST /api/search-index/rebuild': () => {
        going = true;
        return { running: true };
      },
    });
    renderWithProviders(<App />, { route: '/settings/search' });
    expect(await screen.findByText('40 of 50')).toBeInTheDocument();
    expect(screen.getByText(/No: it will be rebuilt/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Rebuild the index' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === '/api/search-index/rebuild')).toBe(true),
    );
    expect(await screen.findByText('Rebuilding')).toBeInTheDocument();
  });
});

describe('Tiers', () => {
  it('lists them, shows why one is unavailable and picks the default', async () => {
    const fetchMock = mockApi({ ...BASE, 'POST /api/tiers/use': {}, 'POST /api/tiers/reset': {} });
    renderWithProviders(<App />, { route: '/settings/tiers' });
    const table = await screen.findByRole('table', { name: 'Processing tiers' });
    expect(within(table).getByText('no runner')).toBeInTheDocument();
    expect(within(table).getAllByText('Default')).toHaveLength(2); // the column and the badge
    await userEvent.click(within(table).getByRole('button', { name: 'Use' }));
    await waitFor(() =>
      expect(
        JSON.parse(fetchMock.mock.calls.find(([p]) => p === '/api/tiers/use')[1].body),
      ).toEqual({ tier: 'github' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Back to local' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === '/api/tiers/reset')).toBe(true),
    );
  });
});

describe('Policy', () => {
  it('is a settings tab showing the policy and its switches', async () => {
    const fetchMock = mockApi({ ...BASE, 'POST /api/policy/refresh': BASE['GET /api/policy'] });
    renderWithProviders(<App />, { route: '/settings/policy' });
    expect(await screen.findByText('Scheduled maintenance.')).toBeInTheDocument();
    const features = screen.getByRole('table', { name: 'Policy features' });
    expect(within(features).getByText('github_tier')).toBeInTheDocument();
    expect(within(features).getByText('Needs 2.0')).toBeInTheDocument();
    const addons = screen.getByRole('table', { name: 'Policy add-ons' });
    expect(within(addons).getByText('Switched off')).toBeInTheDocument();
    expect(screen.getByText('key-1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fetch the latest policy' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === '/api/policy/refresh')).toBe(true),
    );
  });
});

describe('Policy key revocation', () => {
  it('shows the revoked keys and says why the saved policy is not used', async () => {
    mockApi({
      ...BASE,
      'GET /api/policy': {
        ...BASE['GET /api/policy'],
        revoked_key_ids: ['pol-aaaaaaaaaaaaaaaa'],
        trust_message: 'The key that signed the saved policy has been revoked.',
      },
    });
    renderWithProviders(<App />, { route: '/settings/policy' });
    expect(await screen.findByText(/signed the saved policy has been revoked/)).toBeInTheDocument();
    expect(screen.getByText('pol-aaaaaaaaaaaaaaaa')).toBeInTheDocument();
  });
});

describe('Shared metrics', () => {
  it('shows where sharing stands and exactly what would be sent', async () => {
    mockApi(BASE);
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByText('What is shared')).toBeInTheDocument();
    expect(screen.getByText('anon-123')).toBeInTheDocument();
    expect(screen.getByText('Days waiting to be sent')).toBeInTheDocument();
    expect(screen.getByText('On (+10%)')).toBeInTheDocument();
    expect(screen.getByText('en, ta')).toBeInTheDocument();
    expect(screen.getByText(/Next batch: 2.0 KB/)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/2026-10-11 · 12 pages in 2 groups · 1 failure groups/));
    const table = await screen.findByRole('table', { name: 'Usage on 2026-10-11' });
    expect(within(table).getByText('paddle')).toBeInTheDocument();
    expect(within(table).getByText('native')).toBeInTheDocument();
    const failures = screen.getByRole('table', { name: 'Failures on 2026-10-11' });
    expect(within(failures).getByText('password')).toBeInTheDocument();
  });

  it('shows the raw batch on request', async () => {
    mockApi(BASE);
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByText('What is shared');
    expect(screen.queryByLabelText('Raw batch')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'Show the raw data' }));
    expect(screen.getByLabelText('Raw batch')).toHaveTextContent('"install_id": "anon-123"');
  });

  it('sends now and says what happened', async () => {
    const fetchMock = mockApi({ ...BASE, 'POST /api/metrics/send': { status: 'sent', days: 1 } });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(await screen.findByRole('button', { name: 'Send now' }));
    await waitFor(() =>
      expect(
        JSON.parse(fetchMock.mock.calls.find(([p]) => p === '/api/metrics/send')[1].body),
      ).toEqual({ force: true }),
    );
    expect(await screen.findByText('Sent.')).toBeInTheDocument();
  });

  it('cannot send while sharing is off, and says nothing was sent', async () => {
    mockApi({ ...BASE, 'GET /api/metrics': { ...BASE['GET /api/metrics'], opted_in: false } });
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByRole('button', { name: 'Send now' })).toBeDisabled();
    expect(screen.getByText('Off')).toBeInTheDocument();
  });

  it('asks before deleting what was sent', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'POST /api/metrics/delete-data': { status: 'sent', detail: '' },
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(await screen.findByRole('button', { name: 'Delete my data…' }));
    expect(await screen.findByText('Delete the data already sent?')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([p]) => p === '/api/metrics/delete-data')).toBe(false);
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }),
    );
    expect(await screen.findByText('Deletion requested')).toBeInTheDocument();
  });
});

describe('A page that fails to draw', () => {
  it('leaves the menu in place and says so', async () => {
    mockApi({
      ...BASE,
      // A batch without the days it should have: the panel cannot draw it.
      'GET /api/metrics/preview': {
        size_bytes: 1,
        batch: { client: {}, settings: {}, days: [{ day: 'x' }] },
      },
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByText('This page could not be shown.')).toBeInTheDocument();
    expect(screen.getAllByRole('tab', { name: 'Credits' })[0]).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
