import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { CATALOG, mockApi, renderWithProviders } from '../test/helpers.jsx';

const OPTIONS = {
  engines: [
    { id: 'exact', label: 'Exact', available: true, reason: '', options: {}, approximate: false },
    {
      id: 'fuzzy',
      label: 'Similar',
      available: true,
      reason: '',
      options: { threshold: 'balanced' },
      approximate: true,
    },
    {
      id: 'semantic',
      label: 'Meaning',
      available: false,
      reason: 'not installed',
      options: {},
      approximate: true,
    },
  ],
  normalizers: [
    { id: 'case', levels: ['match', 'ignore'], identity: 'match', version: '1', setting: 'auto' },
  ],
  file_types: [
    { id: 'pdf', label: 'PDF', extensions: ['.pdf'], available: true },
    { id: 'txt', label: 'Text', extensions: ['.txt'], available: true },
  ],
  defaults: { engine: 'all', context_chars: 80 },
};

const match = (over = {}) => ({
  file_id: 1,
  document_id: 1,
  file_name: 'report.pdf',
  file_path: '/docs/report.pdf',
  file_type: 'pdf',
  page_number: 3,
  total_pages: 12,
  before: 'the harvest of ',
  matched: 'wheat',
  after: ' rose in autumn',
  truncated_before: true,
  truncated_after: false,
  duplicate_of_path: null,
  source: 'native',
  score: null,
  start: 10,
  end: 15,
  engine: 'exact',
  matched_by: ['exact'],
  modifiers: [],
  ...over,
});

const RESULT = {
  query: 'wheat',
  engine: 'all',
  total: 3,
  levels: {},
  index_rebuilt: false,
  pending: {},
  options: {},
  matches: [
    match(),
    match({
      page_number: 5,
      start: 40,
      engine: 'fuzzy',
      matched_by: ['fuzzy', 'exact'],
      score: 0.83,
      modifiers: ['accents'],
    }),
    match({
      file_name: 'notes.txt',
      file_path: '/docs/notes.txt',
      file_type: 'txt',
      total_pages: 1,
      page_number: 1,
      source: 'native',
    }),
  ],
};

const ROUTES = {
  'GET /api/search/options': OPTIONS,
  'GET /api/sources': { sources: [{ id: 7, name: 'docs', path: '/docs' }] },
  'GET /api/catalog': CATALOG,
  'POST /api/search/run': RESULT,
};

const bodies = (fetchMock) =>
  fetchMock.mock.calls
    .filter(([p]) => p === '/api/search/run')
    .map(([, init]) => JSON.parse(init.body));

beforeEach(() => localStorage.clear());

const type = async (text) =>
  userEvent.type(await screen.findByRole('searchbox', { name: 'Search text' }), text);

describe('Search', () => {
  it('is a menu item with the box, the filters, and a keyboard button that is off', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    expect(await screen.findByRole('searchbox', { name: 'Search text' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'File types' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Engine' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled(); // nothing typed
    expect(
      screen.getByRole('button', { name: 'On-screen keyboard (coming later)' }),
    ).toBeDisabled();
    expect(screen.getAllByRole('tab', { name: 'Search' })[0]).toBeInTheDocument();
  });

  it('searches on Enter and shows the file, page, text with the match marked, and how it was found', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    expect(await within(table).findByText('report.pdf')).toBeInTheDocument();
    expect(within(table).getByText('notes.txt')).toBeInTheDocument();
    expect(within(table).getByText('3 of 12')).toBeInTheDocument();
    expect(table.querySelector('mark')).toHaveTextContent('wheat');
    expect(within(table).getByText('Similar 83%')).toBeInTheDocument();
    expect(within(table).getByText('+1')).toBeInTheDocument();
    expect(within(table).getByText('2 matches')).toBeInTheDocument();
    expect(screen.getByText(/3 matches in 2 files/)).toBeInTheDocument();
    expect(bodies(fetchMock)[0]).toEqual({ query: 'wheat', limit: 50, offset: 0 });
  });

  it('sends the file types, engine, case and sources that were chosen', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'File types' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'PDF' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Text' }));
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('combobox', { name: 'Engine' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Similar' }));
    await userEvent.click(screen.getByRole('button', { name: 'Match case' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Sources' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'docs' }));
    await userEvent.keyboard('{Escape}');
    await type('wheat');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(1));
    expect(bodies(fetchMock)[0]).toMatchObject({
      query: 'wheat',
      engine: 'fuzzy',
      case_sensitive: true,
      file_types: ['pdf', 'txt'],
      sources: [7],
    });
  });

  it('puts an engine setting and a normalizer level from the options flyout in the request', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'Engine' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Similar' }));
    await userEvent.click(screen.getByRole('button', { name: 'Search options' }));
    await userEvent.type(await screen.findByLabelText('threshold'), 'loose');
    await userEvent.click(screen.getByRole('combobox', { name: 'Normalizer case' }));
    await userEvent.click(await screen.findByRole('option', { name: 'ignore' }));
    await userEvent.keyboard('{Escape}');
    await type('wheat{Enter}');
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(1));
    expect(bodies(fetchMock)[0]).toMatchObject({
      engine: 'fuzzy',
      options: { fuzzy: { threshold: 'loose' } },
      normalize: { case: 'ignore' },
    });
  });

  it('says so when nothing matched, and when pages are not ready for an engine', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/search/run': {
        ...RESULT,
        total: 0,
        matches: [],
        pending: { semantic: 12 },
        index_rebuilt: true,
      },
    });
    renderWithProviders(<App />, { route: '/search' });
    await type('zzz{Enter}');
    expect(await screen.findByText(/^No matches\./)).toBeInTheDocument();
    expect(screen.getByText(/Meaning \(12 pages\)/)).toBeInTheDocument();
    expect(screen.getByText(/index was rebuilt/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export every match' })).toBeDisabled();
  });

  it('shows why a search failed', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/search/run': new Response(
        JSON.stringify({ error: 'The Similar engine cannot search this.' }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/search' });
    await type('a{Enter}');
    expect(await screen.findByText('The Similar engine cannot search this.')).toBeInTheDocument();
  });

  it('keeps recent searches, and runs one when it is picked', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    await screen.findByRole('table', { name: 'Search results' });
    await userEvent.click(screen.getByRole('button', { name: 'Recent searches' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'wheat' }));
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(2));
    expect(JSON.parse(localStorage.getItem('vethuq.recent-searches'))).toEqual(['wheat']);
  });

  it('opens the menu of a result, with Open off in a browser and Preview coming later', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    await userEvent.pointer({
      keys: '[MouseRight]',
      target: await within(table).findByText('notes.txt'),
    });
    expect(await screen.findByRole('menuitem', { name: 'Open' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByRole('menuitem', { name: 'Preview (coming soon)' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByRole('menuitem', { name: 'Copy path' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Open in Sources' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('shows the details of a match', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    await userEvent.pointer({
      keys: '[MouseRight]',
      target: (await within(table).findAllByText('5 of 12'))[0],
    });
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Details' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('/docs/report.pdf')).toBeInTheDocument();
    expect(within(dialog).getByText('accents')).toBeInTheDocument();
    expect(within(dialog).getByText('83%')).toBeInTheDocument();
  });
});
