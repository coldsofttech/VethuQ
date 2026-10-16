import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const ADDONS = {
  installed: [],
  bundles: [],
  install: { ok: true, reason: '' },
};
const JOB = { running: false, action: null, target: null, log: [], error: null, finished: false };

const entry = (over) => ({
  id: 'x',
  label: 'X',
  summary: 'An add-on.',
  description: '',
  kind: '',
  licence: '',
  bundles: [],
  status: 'available',
  state: 'not_installed',
  installed: false,
  listed: true,
  installed_version: null,
  min_client: null,
  requires_newer_client: false,
  size_bytes: null,
  docs_url: null,
  request_url: null,
  ...over,
});

const CATALOG = {
  catalog: { source: 'cache', status: 'current', detail: '', update_required: false },
  addons: [
    entry({
      id: 'pdf',
      label: 'PDF',
      summary: 'Read PDF files.',
      state: 'enabled',
      installed: true,
      licence: 'free',
      kind: 'file-type',
    }),
    entry({
      id: 'docx',
      label: 'Word documents',
      summary: 'Read .docx files.',
      description: 'Reads tables, headers and footnotes.',
      licence: 'licensed',
      bundles: ['office'],
      request_url: 'https://example.test/ask-docx',
      docs_url: 'https://example.test/docx',
    }),
    entry({
      id: 'semantic',
      label: 'Semantic search',
      summary: 'By meaning.',
      status: 'coming_soon',
    }),
    entry({
      id: 'newer',
      label: 'Needs newer',
      summary: 'Needs a newer VethuQ.',
      requires_newer_client: true,
      min_client: '9.0.0',
    }),
  ],
  bundles: [
    {
      id: 'office',
      label: 'Office',
      summary: 'Word, Excel and PowerPoint.',
      description: '',
      addons: ['docx'],
      installed: [],
      complete: false,
      status: 'available',
      docs_url: null,
      request_url: 'https://example.test/ask-office',
    },
  ],
};

const ROUTES = {
  'GET /api/addons': ADDONS,
  'GET /api/addons/job': JOB,
  'GET /api/addons/catalog': CATALOG,
};

describe('Discover add-ons', () => {
  it('is a tab that lists every add-on with its description and state', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons/discover' });

    const card = await screen.findByLabelText('Word documents');
    expect(within(card).getByText('Read .docx files.')).toBeInTheDocument();
    expect(within(card).getByText('Not installed')).toBeInTheDocument();
    expect(within(card).getByText('Licensed')).toBeInTheDocument();
    expect(within(card).getByText('Bundle: office')).toBeInTheDocument();
    expect(within(card).getByText('Reads tables, headers and footnotes.')).toBeInTheDocument();
    const pdf = screen.getByLabelText('PDF');
    expect(within(pdf).getByText('Installed')).toBeInTheDocument();
    expect(within(pdf).getByText('Free')).toBeInTheDocument();
  });

  it('shows where to ask for what is not installed, and not for what is', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons/discover' });
    const docx = await screen.findByLabelText('Word documents');

    const ask = within(docx).getByRole('link', { name: 'Ask for it' });
    expect(ask).toHaveAttribute('href', 'https://example.test/ask-docx');
    expect(within(docx).getByRole('link', { name: 'Learn more' })).toHaveAttribute(
      'href',
      'https://example.test/docx',
    );
    expect(
      within(screen.getByLabelText('PDF')).queryByRole('link', { name: 'Ask for it' }),
    ).toBeNull();
    expect(
      within(screen.getByLabelText('Semantic search')).getByText('Ask your administrator for it.'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText('Semantic search')).getByText('Coming soon'),
    ).toBeInTheDocument();
  });

  it('says when an add-on needs a newer VethuQ', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons/discover' });

    expect(await screen.findByText('Needs VethuQ 9.0.0 or newer.')).toBeInTheDocument();
  });

  it('lists the bundles with how much of each is installed', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons/discover' });
    const office = await screen.findByLabelText('Office bundle');

    expect(within(office).getByText('0 of 1 installed')).toBeInTheDocument();
    expect(within(office).getByText('Includes: docx')).toBeInTheDocument();
    expect(within(office).getByRole('link', { name: 'Ask for it' })).toHaveAttribute(
      'href',
      'https://example.test/ask-office',
    );
  });

  it('filters by text and by what is not installed', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/addons/discover' });
    await screen.findByLabelText('Word documents');

    await userEvent.type(screen.getByLabelText('Search add-ons'), 'semantic');
    expect(screen.queryByLabelText('Word documents')).toBeNull();
    expect(screen.getByLabelText('Semantic search')).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText('Search add-ons'));
    await userEvent.click(screen.getByRole('switch', { name: 'Only those not installed' }));
    expect(screen.queryByLabelText('PDF')).toBeNull();
    expect(screen.getByLabelText('Word documents')).toBeInTheDocument();
  });

  it('says so when no list has been received yet, and checks on demand', async () => {
    let refreshed = false;
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/addons/catalog': {
        ...CATALOG,
        catalog: { source: 'baseline', status: 'current', detail: '', update_required: false },
        bundles: [],
      },
      'POST /api/addons/catalog/refresh': () => {
        refreshed = true;
        return { ...CATALOG, catalog: { ...CATALOG.catalog, status: 'updated' } };
      },
    });
    renderWithProviders(<App />, { route: '/addons/discover' });

    expect(
      await screen.findByText(/No list of available add-ons has been received yet/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));

    await waitFor(() => expect(refreshed).toBe(true));
    expect(
      JSON.parse(fetchMock.mock.calls.find(([p]) => p === '/api/addons/catalog/refresh')[1].body),
    ).toEqual({ force: true });
    await waitFor(() =>
      expect(screen.queryByText(/No list of available add-ons has been received yet/)).toBeNull(),
    );
  });

  it('warns when the check could not be made', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/addons/catalog/refresh': {
        ...CATALOG,
        catalog: {
          ...CATALOG.catalog,
          status: 'skipped',
          detail: 'the update check is turned off',
        },
      },
    });
    renderWithProviders(<App />, { route: '/addons/discover' });
    await userEvent.click(await screen.findByRole('button', { name: 'Check now' }));

    expect(await screen.findByText('Could not get a newer list')).toBeInTheDocument();
    expect(screen.getByText('the update check is turned off')).toBeInTheDocument();
  });

  it('asks for a newer VethuQ when the list needs one', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/addons/catalog': {
        ...CATALOG,
        catalog: { ...CATALOG.catalog, update_required: true },
      },
    });
    renderWithProviders(<App />, { route: '/addons/discover' });

    expect(
      await screen.findByText('A newer VethuQ is needed to read the newest list.'),
    ).toBeInTheDocument();
  });
});
