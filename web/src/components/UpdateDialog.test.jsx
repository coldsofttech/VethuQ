import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { UpdateDialog } from './UpdateDialog.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const AVAILABLE = {
  status: 'update_available',
  notify: true,
  offer_install: true,
  latest: '2.0.0',
  current: '1.0.0',
  message: 'VethuQ 2.0.0 is available (you have 1.0.0).',
  release_notes_url: 'https://example.com/notes',
};
const INSTALLER = { install_type: 'installer', steps: [], commands: [] };
const PIP = {
  install_type: 'pip',
  steps: [],
  commands: ['python -m pip install --upgrade vethuq'],
};
const TASKS = { 'update-install': { running: false, result: null, error: null, finished: false } };

const routes = (status, help, extra = {}) => ({
  'GET /api/updates': status,
  'GET /api/updates/help': help,
  'GET /api/maintenance/tasks': TASKS,
  ...extra,
});

describe('UpdateDialog', () => {
  it('shows nothing when there is no update to announce', async () => {
    const fetchMock = mockApi(routes({ ...AVAILABLE, notify: false }, INSTALLER));
    renderWithProviders(<UpdateDialog />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByText(/is available/)).toBeNull();
  });

  it('says nothing when the service cannot answer', async () => {
    mockApi({});
    renderWithProviders(<UpdateDialog />);

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('offers Install now, Later and Skip this version to the installed build', async () => {
    mockApi(routes(AVAILABLE, INSTALLER));
    renderWithProviders(<UpdateDialog />);

    expect(await screen.findByText('VethuQ 2.0.0 is available')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Install now' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Later' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Skip this version' })).toBeTruthy();
  });

  it('Later hides the notice for a day and closes', async () => {
    const fetchMock = mockApi(
      routes(AVAILABLE, INSTALLER, { 'POST /api/updates/later': AVAILABLE }),
    );
    renderWithProviders(<UpdateDialog />);

    await userEvent.click(await screen.findByRole('button', { name: 'Later' }));

    await waitFor(() => expect(screen.queryByText('VethuQ 2.0.0 is available')).toBeNull());
    const call = fetchMock.mock.calls.find(([path]) => path === '/api/updates/later');
    expect(JSON.parse(call[1].body)).toEqual({ days: 1 });
  });

  it('Skip this version asks the service to skip and closes', async () => {
    const fetchMock = mockApi(
      routes(AVAILABLE, INSTALLER, { 'POST /api/updates/skip': AVAILABLE }),
    );
    renderWithProviders(<UpdateDialog />);

    await userEvent.click(await screen.findByRole('button', { name: 'Skip this version' }));

    await waitFor(() => expect(screen.queryByText('VethuQ 2.0.0 is available')).toBeNull());
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/updates/skip')).toBe(true);
  });

  it('Install now starts the install and says VethuQ will restart', async () => {
    const fetchMock = mockApi(
      routes(AVAILABLE, INSTALLER, {
        'POST /api/updates/install': { running: true, result: null, error: null, finished: false },
      }),
    );
    renderWithProviders(<UpdateDialog />);

    await userEvent.click(await screen.findByRole('button', { name: 'Install now' }));

    expect(await screen.findByText(/VethuQ will close and open again/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/updates/install')).toBe(true);
  });

  it('shows the reason when the install is refused', async () => {
    mockApi(
      routes(AVAILABLE, INSTALLER, {
        'POST /api/updates/install': new Response(
          JSON.stringify({ error: 'The installer does not match its checksum; it was not run.' }),
          { status: 502 },
        ),
      }),
    );
    renderWithProviders(<UpdateDialog />);

    await userEvent.click(await screen.findByRole('button', { name: 'Install now' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/checksum/);
  });

  it('shows the commands, not Install now, for a pip install', async () => {
    mockApi(routes({ ...AVAILABLE, offer_install: false }, PIP));
    renderWithProviders(<UpdateDialog />);

    expect(await screen.findByText('python -m pip install --upgrade vethuq')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Install now' })).toBeNull();
  });

  it('cannot put off a version that is below the minimum', async () => {
    mockApi(routes({ ...AVAILABLE, status: 'below_minimum' }, INSTALLER));
    renderWithProviders(<UpdateDialog />);

    expect(await screen.findByText('Please update VethuQ')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Later' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Skip this version' })).toBeNull();
  });
});
