import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const JOB = { running: false, action: null, target: null, log: [], error: null, finished: false };
const ADDONS = { installed: [], bundles: [], install: { ok: true, reason: '' } };
const LICENCE = {
  licence_id: 'LIC-1',
  kind: 'addon',
  status: 'ok',
  detail: '',
  valid_until: '2027-01-01',
  lists: ['doc', 'docx'],
  installed_on: ['doc', 'docx'],
};
const BASE = { 'GET /api/addons': ADDONS, 'GET /api/addons/job': JOB };
const bodyOf = (fetchMock, path) =>
  JSON.parse(fetchMock.mock.calls.find(([p]) => p === path)?.[1].body ?? 'null');

describe('Licences tab', () => {
  it('lists the installed licences with what they unlock and where they are installed', async () => {
    mockApi({ ...BASE, 'GET /api/licences': [LICENCE] });
    renderWithProviders(<App />, { route: '/addons/licences' });
    const table = await screen.findByRole('table', { name: 'Installed licences' });
    expect(within(table).getByText('LIC-1')).toBeInTheDocument();
    expect(within(table).getAllByText('doc, docx')).toHaveLength(2);
    expect(within(table).getByText('2027-01-01')).toBeInTheDocument();
  });

  it('says so when there is none', async () => {
    mockApi({ ...BASE, 'GET /api/licences': [] });
    renderWithProviders(<App />, { route: '/addons/licences' });
    expect(await screen.findByText('No licence is installed.')).toBeInTheDocument();
  });

  it('installs a pasted key on every add-on it lists and shows the result', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'GET /api/licences': [],
      'POST /api/licences/install': {
        installed: 1,
        results: [
          { addon_id: 'docx', status: 'stored', detail: '' },
          { addon_id: 'rtf', status: 'not_installed', detail: '' },
        ],
      },
    });
    renderWithProviders(<App />, { route: '/addons/licences' });
    const install = await screen.findByRole('button', { name: 'Install' });
    expect(install).toBeDisabled();
    await userEvent.type(screen.getByRole('textbox', { name: 'Licence key' }), '  VQLIC1.abc  ');
    await userEvent.click(install);
    await waitFor(() =>
      expect(bodyOf(fetchMock, '/api/licences/install')).toEqual({ token: 'VQLIC1.abc' }),
    );
    const result = await screen.findByRole('table', { name: 'Licence install result' });
    expect(within(result).getByText('Installed')).toBeInTheDocument();
    expect(within(result).getByText('Add-on not installed here')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Licence key' })).toHaveValue('');
  });

  it('reads a .vqlic file into the box', async () => {
    mockApi({ ...BASE, 'GET /api/licences': [] });
    renderWithProviders(<App />, { route: '/addons/licences' });
    const input = await screen.findByLabelText('Licence file');
    const file = new File(['VQLIC1.fromfile\n'], 'acme.vqlic', { type: 'text/plain' });
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Licence key' })).toHaveValue('VQLIC1.fromfile'),
    );
  });

  it('shows why an invalid licence was refused', async () => {
    mockApi({
      ...BASE,
      'GET /api/licences': [],
      'POST /api/licences/install': new Response(
        JSON.stringify({ error: 'The licence is not valid: expired on 2025-01-01.' }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/addons/licences' });
    await userEvent.type(await screen.findByRole('textbox', { name: 'Licence key' }), 'VQLIC1.old');
    await userEvent.click(screen.getByRole('button', { name: 'Install' }));
    expect(await screen.findByText(/expired on 2025-01-01/)).toBeInTheDocument();
  });

  it('prepares a request, says it is public, shows exactly what it holds and links to it', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'GET /api/licences': [],
      'POST /api/licences/request': {
        kind: 'new',
        code: 'VQREQ1.abc.12345678',
        url: 'https://github.com/coldsofttech/VethuQ/issues/new?template=licence-request.yml',
        privacy: 'This opens a PUBLIC issue.\nIt will contain only: …',
        fields: { request_code: 'VQREQ1.abc.12345678', addons: 'docx' },
      },
    });
    renderWithProviders(<App />, { route: '/addons/licences' });
    await userEvent.type(await screen.findByRole('textbox', { name: /Add-ons/ }), 'docx, doc');
    await userEvent.type(screen.getByRole('textbox', { name: /Note/ }), 'for my team');
    await userEvent.click(screen.getByRole('button', { name: 'Prepare request' }));
    expect(await screen.findByText(/This opens a PUBLIC issue/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, '/api/licences/request')).toEqual({
      kind: 'new',
      addons: ['docx', 'doc'],
      bundle: null,
      wallet: null,
      note: 'for my team',
      github: false,
      runner_owner: null,
    });
    const fields = screen.getByRole('table', { name: 'What the issue will contain' });
    expect(within(fields).getByText('VQREQ1.abc.12345678')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Open the public issue' });
    expect(link).toHaveAttribute('href', expect.stringContaining('github.com/coldsofttech/VethuQ'));
    expect(link).toHaveAttribute('rel', 'noreferrer');
    expect(screen.getByRole('button', { name: 'Copy the request code' })).toBeInTheDocument();
  });

  it('asks for the wallet only on a top-up, and the runner owner only with a GitHub id', async () => {
    mockApi({ ...BASE, 'GET /api/licences': [] });
    renderWithProviders(<App />, { route: '/addons/licences' });
    await screen.findByRole('button', { name: 'Prepare request' });
    expect(screen.queryByRole('textbox', { name: /Wallet/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /Runner repository owner/ })).toBeNull();
    await userEvent.click(screen.getByRole('checkbox', { name: /Include my GitHub id/ }));
    expect(screen.getByRole('textbox', { name: /Runner repository owner/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: 'A top-up' }));
    expect(screen.getByRole('textbox', { name: /Wallet/ })).toBeInTheDocument();
  });

  it('shows a refused request', async () => {
    mockApi({
      ...BASE,
      'GET /api/licences': [],
      'POST /api/licences/request': new Response(
        JSON.stringify({ error: "'../x' isn't an add-on or bundle id." }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/addons/licences' });
    await userEvent.click(await screen.findByRole('button', { name: 'Prepare request' }));
    expect(await screen.findByText(/isn't an add-on or bundle id/)).toBeInTheDocument();
  });
});
