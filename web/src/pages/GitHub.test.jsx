import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const RUNNER = {
  owner: 'me',
  repo: 'vethuq-runner',
  private: true,
  workflow_ref: 'v1',
  image: 'ghcr.io/x/worker:1',
  protocol: 1,
  key_fingerprint: 'ab12',
  set_up_at: '2026-10-01T10:00:00+00:00',
  url: 'https://github.com/me/vethuq-runner',
};

const OVERVIEW = {
  installed: true,
  enabled: true,
  reason: '',
  token: { environment: false, session: false, stored: false, store_available: false },
  runner: null,
  versions: [{ workflow_ref: 'v1', status: 'current' }],
  tier: { id: 'github', available: false, reason: 'no runner' },
};

const OFF = { installed: false, enabled: false, reason: 'The GitHub add-on is not installed.' };

const body = (fetchMock, path) =>
  JSON.parse(fetchMock.mock.calls.find(([p]) => p === path)[1].body);

describe('GitHub', () => {
  it('has no menu item without the add-on', async () => {
    mockApi({ 'GET /api/github/availability': OFF });
    renderWithProviders(<App />, { route: '/' });
    await screen.findByRole('tab', { name: 'Logs' });
    expect(screen.queryByRole('tab', { name: 'GitHub' })).not.toBeInTheDocument();
  });

  it('has a menu item when the add-on runs', async () => {
    mockApi({ 'GET /api/github/availability': { installed: true, enabled: true, reason: '' } });
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByRole('tab', { name: 'GitHub' })).toBeInTheDocument();
  });

  it('explains why it cannot be used', async () => {
    mockApi({
      'GET /api/github/availability': OFF,
      'GET /api/github': { ...OFF, token: {}, runner: null, versions: [] },
    });
    renderWithProviders(<App />, { route: '/github' });
    expect(await screen.findByText('The GitHub add-on is not installed.')).toBeInTheDocument();
  });

  it('sets the runner up with the token typed, and does not keep it unless asked', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': OVERVIEW,
      'POST /api/github/setup': RUNNER,
    });
    renderWithProviders(<App />, { route: '/github' });
    await userEvent.type(await screen.findByLabelText('GitHub token'), 'github_pat_abc');
    await userEvent.clear(screen.getByLabelText('Repository name'));
    await userEvent.type(screen.getByLabelText('Repository name'), 'my-runner');
    await userEvent.click(screen.getByRole('button', { name: 'Set up' }));
    await waitFor(() => {
      expect(body(fetchMock, '/api/github/setup')).toMatchObject({
        repo: 'my-runner',
        token: 'github_pat_abc',
        private: true,
        create: true,
        adopt: false,
      });
    });
  });

  it('saves a token in Credential Manager when asked, and says so', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': {
        ...OVERVIEW,
        token: { environment: false, session: false, stored: false, store_available: true },
      },
      'POST /api/github/token': {
        environment: false,
        session: false,
        stored: true,
        store_available: true,
      },
      'POST /api/github/token/forget': {
        environment: false,
        session: false,
        stored: false,
        store_available: true,
      },
    });
    renderWithProviders(<App />, { route: '/github' });
    await userEvent.type(await screen.findByLabelText('GitHub token'), 'tok');
    await userEvent.click(screen.getByRole('button', { name: 'Save in Credential Manager' }));
    await waitFor(() =>
      expect(body(fetchMock, '/api/github/token')).toEqual({ token: 'tok', store: true }),
    );
    expect(
      await screen.findByText('A token is saved in Windows Credential Manager.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('GitHub token')).toHaveValue('');
    await userEvent.click(screen.getByRole('button', { name: 'Forget' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === '/api/github/token/forget')).toBe(true),
    );
    expect(await screen.findByText(/No token yet/)).toBeInTheDocument();
  });

  it('keeps a token for the session only when asked', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': OVERVIEW,
      'POST /api/github/token': {
        environment: true,
        session: true,
        stored: false,
        store_available: false,
      },
    });
    renderWithProviders(<App />, { route: '/github' });
    await userEvent.type(await screen.findByLabelText('GitHub token'), 'tok');
    expect(
      screen.queryByRole('button', { name: 'Save in Credential Manager' }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Use for this session' }));
    await waitFor(() =>
      expect(body(fetchMock, '/api/github/token')).toEqual({ token: 'tok', store: false }),
    );
    expect(await screen.findByText('A token is kept for this session only.')).toBeInTheDocument();
  });

  it('offers to save the token when setting up, and passes the choice', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': {
        ...OVERVIEW,
        token: { environment: false, session: false, stored: false, store_available: true },
      },
      'POST /api/github/setup': RUNNER,
    });
    renderWithProviders(<App />, { route: '/github' });
    await userEvent.type(await screen.findByLabelText('GitHub token'), 'tok');
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'Save the token in Windows Credential Manager' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Set up' }));
    await waitFor(() =>
      expect(body(fetchMock, '/api/github/setup')).toMatchObject({ token: 'tok', store: true }),
    );
  });

  it('shows the runner, checks it, and updates it', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': {
        ...OVERVIEW,
        runner: RUNNER,
        tier: { id: 'github', available: true, reason: '' },
      },
      'POST /api/github/status': {
        ok: false,
        repo_found: true,
        secret_set: false,
        caller_ok: true,
        up_to_date: false,
        problems: ['The master key secret is missing.'],
      },
      'POST /api/github/update': RUNNER,
    });
    renderWithProviders(<App />, { route: '/github' });
    expect(await screen.findByRole('link', { name: 'me/vethuq-runner' })).toHaveAttribute(
      'href',
      RUNNER.url,
    );
    expect(screen.getByText('Private')).toBeInTheDocument();
    expect(screen.getByText('ab12')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Check on GitHub' }));
    expect(await screen.findByText('The master key secret is missing.')).toBeInTheDocument();
    expect(screen.getByText('Key secret missing')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Update the runner' }));
    await waitFor(() =>
      expect(body(fetchMock, '/api/github/update')).toMatchObject({ workflow_ref: '' }),
    );
  });

  it('asks before removing and passes what to delete', async () => {
    const fetchMock = mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': { ...OVERVIEW, runner: RUNNER },
      'POST /api/github/remove': RUNNER,
    });
    renderWithProviders(<App />, { route: '/github' });
    await userEvent.click(await screen.findByRole('button', { name: 'Remove…' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(
      within(dialog).getByRole('checkbox', { name: 'Also delete the repository on GitHub' }),
    );
    expect(fetchMock.mock.calls.some(([p]) => p === '/api/github/remove')).toBe(false);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove' }));
    await waitFor(() =>
      expect(body(fetchMock, '/api/github/remove')).toMatchObject({
        delete_repo: true,
        delete_key: false,
      }),
    );
  });

  it('shows the jobs sent to GitHub', async () => {
    mockApi({
      'GET /api/github/availability': { enabled: true },
      'GET /api/github': { ...OVERVIEW, runner: RUNNER },
      'GET /api/github/jobs': {
        jobs: [
          {
            id: 3,
            run_id: 9,
            status: 'failed',
            images: 12,
            size_bytes: 2048,
            credits: 12,
            submitted_at: '2026-10-12T10:00:00+00:00',
            completed_at: null,
            error: 'timed out',
          },
        ],
      },
    });
    renderWithProviders(<App />, { route: '/github/jobs' });
    const table = await screen.findByRole('table', { name: 'GitHub jobs' });
    expect(within(table).getByText('timed out')).toBeInTheDocument();
    expect(within(table).getByText('failed')).toBeInTheDocument();
    expect(within(table).getByText('2.0 KB')).toBeInTheDocument();
  });
});
