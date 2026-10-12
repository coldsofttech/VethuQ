import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const JOB = { running: false, action: null, target: null, log: [], error: null, finished: false };

const BASE = {
  detail: '',
  disabled: false,
  licence: false,
  switched_off: false,
  message: null,
  latest: null,
  update: false,
  restart: false,
};

const DATA = {
  installed: [
    {
      ...BASE,
      id: 'pdf',
      name: 'vethuq-addon-pdf',
      version: '0.1.0',
      status: 'loaded',
      latest: '0.2.0',
      update: true,
    },
    {
      ...BASE,
      id: 'csv',
      name: 'vethuq-addon-csv',
      version: '0.1.0',
      status: 'loaded',
      disabled: true,
      restart: true,
    },
    {
      ...BASE,
      id: 'broken',
      name: 'vethuq-addon-broken',
      version: '0.1.0',
      status: 'failed',
      detail: 'ImportError',
    },
    {
      ...BASE,
      id: 'old',
      name: 'vethuq-addon-old',
      version: '0.1.0',
      status: 'loaded',
      switched_off: true,
      message: 'Withdrawn.',
    },
    { ...BASE, id: 'english', name: 'vethuq-addon-english', version: '0.1.0', status: 'loaded' },
    {
      ...BASE,
      id: 'html',
      name: 'vethuq-addon-html',
      version: '0.1.0',
      status: 'loaded',
      licence: true,
    },
  ],
  packs: [
    {
      id: 'images',
      note: 'Read image files.',
      packages: [{ name: 'vethuq-bundle-image', version: null }],
      installed: false,
    },
    {
      id: 'fuzzy',
      note: 'Similar words.',
      packages: [{ name: 'vethuq-addon-fuzzy', version: '0.1.0' }],
      installed: true,
    },
  ],
  install: { ok: true, reason: '' },
};

const ROUTES = { 'GET /api/addons': DATA, 'GET /api/addons/job': JOB };
const bodyOf = (fetchMock, path) =>
  JSON.parse(fetchMock.mock.calls.find(([p]) => p === path)?.[1].body ?? 'null');

describe('Add-ons', () => {
  it('is its own menu item with an installed list', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons' });
    const table = await screen.findByRole('table', { name: 'Installed add-ons' });
    expect(within(table).getByText('vethuq-addon-pdf')).toBeInTheDocument();
    expect(within(table).getByText('Failed')).toBeInTheDocument();
    expect(within(table).getByText('Switched off by VethuQ')).toBeInTheDocument();
    expect(within(table).getByText('Turns off at restart')).toBeInTheDocument();
    expect(within(table).getByText('Entered')).toBeInTheDocument();
    expect(screen.getByText('Restart VethuQ for the changes to take effect.')).toBeInTheDocument();
    expect(screen.getAllByRole('tab', { name: 'Add-ons' })[0]).toBeInTheDocument();
  });

  it('turns one off with the switch, and keeps the ones that cannot be', async () => {
    const fetchMock = mockApi({ ...ROUTES, 'POST /api/addons/pdf/enabled': {} });
    renderWithProviders(<App />, { route: '/addons/installed' });
    await screen.findByRole('table', { name: 'Installed add-ons' });
    expect(screen.getByRole('switch', { name: 'Turn english on or off' })).toBeDisabled();
    expect(screen.getByRole('switch', { name: 'Turn old on or off' })).toBeDisabled();
    await userEvent.click(screen.getByRole('switch', { name: 'Turn pdf on or off' }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, '/api/addons/pdf/enabled')).toEqual({ enabled: false }),
    );
    expect(await screen.findByText('pdf will be off after a restart')).toBeInTheDocument();
  });

  it('updates after asking, and says to restart when done', async () => {
    let going = false;
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/addons/job': () =>
        going ? { ...JOB, running: true, action: 'update', target: 'pdf' } : JOB,
      'POST /api/addons/pdf/update': () => {
        going = true;
        return { ...JOB, running: true, action: 'update', target: 'pdf' };
      },
    });
    renderWithProviders(<App />, { route: '/addons/installed' });
    await userEvent.click(await screen.findByRole('button', { name: 'Update pdf to 0.2.0' }));
    expect(await screen.findByText('Update pdf?')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([p]) => p === '/api/addons/pdf/update')).toBe(false);
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Update' }),
    );
    expect(await screen.findByText(/Updating pdf/)).toBeInTheDocument();
  });

  it('lists the packs and installs one after asking', async () => {
    let going = false;
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/addons/job': () =>
        going ? { ...JOB, running: true, action: 'install', target: 'images' } : JOB,
      'POST /api/addons/packs/images/install': () => {
        going = true;
        return { ...JOB, running: true, action: 'install', target: 'images' };
      },
    });
    renderWithProviders(<App />, { route: '/addons/get' });
    const table = await screen.findByRole('table', { name: 'Add-on packs' });
    expect(within(table).getByText('Installed')).toBeInTheDocument();
    expect(within(table).getByText('Not installed')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Install fuzzy' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Install images' }));
    await userEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Install' }),
    );
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === '/api/addons/packs/images/install')).toBe(
        true,
      ),
    );
    expect(await screen.findByText(/Installing images/)).toBeInTheDocument();
  });

  it('cannot install in a packaged copy and says why', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/addons': {
        ...DATA,
        install: { ok: false, reason: 'This copy of VethuQ is packaged.' },
      },
    });
    renderWithProviders(<App />, { route: '/addons/get' });
    expect(await screen.findByText('This copy of VethuQ is packaged.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install images' })).toBeDisabled();
  });

  it('shows why a job failed, with the end of the output', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/addons/job': {
        ...JOB,
        finished: true,
        action: 'install',
        error: 'pip could not finish.',
        log: ['ERROR: no match'],
      },
    });
    renderWithProviders(<App />, { route: '/addons/get' });
    expect(await screen.findByText('pip could not finish.')).toBeInTheDocument();
    expect(screen.getByText('ERROR: no match')).toBeInTheDocument();
  });
});
