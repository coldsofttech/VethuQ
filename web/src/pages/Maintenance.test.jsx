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
    status: 'update_available',
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
