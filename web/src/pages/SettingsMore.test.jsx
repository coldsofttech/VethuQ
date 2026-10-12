import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const setting = (overrides) => ({
  description: 'A description.',
  is_default: true,
  advanced: false,
  note: '',
  locked: '',
  group: '',
  group_note: '',
  resettable: true,
  readonly: false,
  ...overrides,
});

const PLATFORM = { kind: 'desktop', window_controls: false, folder_dialog: true };

const GENERAL = (overrides = {}) => ({
  section: 'general',
  settings: [
    setting({
      id: 'languages.languages',
      label: 'Languages to read documents in',
      type: 'multichoice',
      value: ['en'],
      default: ['en'],
      group: 'Languages',
      options: [{ value: 'en', label: 'English', available: true, reason: '' }],
    }),
    setting({
      id: 'location.data',
      label: 'Data folder',
      type: 'path',
      value: 'C:\\Users\\me\\AppData\\Local\\VethuQ',
      default: 'C:\\Users\\me\\AppData\\Local\\VethuQ',
      group: 'Data',
      can_move: true,
      note: 'Stop indexing before moving it.',
      ...overrides.data,
    }),
    setting({
      id: 'location.backups',
      label: 'Backups folder',
      type: 'path',
      value: 'C:\\Users\\me\\AppData\\Local\\VethuQ\\db\\backups',
      default: 'C:\\Users\\me\\AppData\\Local\\VethuQ\\db\\backups',
      group: 'Data',
      can_move: false,
    }),
    setting({
      id: 'metrics.opt_in',
      label: 'Share anonymous usage metrics',
      type: 'boolean',
      value: false,
      default: false,
      group: 'Privacy',
    }),
  ],
});

const SEARCH = () => ({
  section: 'search',
  settings: [
    setting({
      id: 'search.engine',
      label: 'Default search engine',
      type: 'choice',
      value: 'all',
      default: 'all',
      group: 'Searching',
      options: [
        { value: 'all', label: 'All engines', available: true, reason: '' },
        { value: 'like', label: 'Contains (like)', available: true, reason: '' },
      ],
    }),
    setting({
      id: 'search.normalize.case',
      label: 'Letter case',
      type: 'choice',
      value: 'auto',
      default: 'auto',
      group: 'How text is matched',
      group_note: 'What counts as the same character in a search.',
      options: [
        { value: 'auto', label: 'Automatic (each engine decides)', available: true, reason: '' },
        { value: 'ignore', label: 'Ignore case', available: true, reason: '' },
      ],
    }),
    setting({
      id: 'search.option.fuzzy.threshold',
      label: 'Threshold',
      type: 'text',
      value: 'balanced',
      default: 'balanced',
      group: 'Similar (fuzzy) engine',
    }),
  ],
});

const ADDONS = () => ({
  section: 'addons',
  settings: [
    setting({
      id: 'backup.enabled',
      label: 'Enabled',
      type: 'boolean',
      value: true,
      default: null,
      is_default: false,
      group: 'Database backups (licensed)',
    }),
    setting({
      id: 'backup.interval-minutes',
      label: 'Interval minutes',
      type: 'integer',
      value: 720,
      default: null,
      is_default: false,
      unit: 'minutes',
      group: 'Database backups (licensed)',
    }),
    setting({
      id: 'autoscale.cpu-percent',
      label: 'Cpu percent',
      type: 'integer',
      value: 80,
      default: null,
      is_default: false,
      min: 20,
      max: 100,
      group: 'Adaptive workers',
    }),
    setting({
      id: 'autoscale.note',
      label: 'Note',
      type: 'text',
      value: 'hello',
      default: null,
      resettable: false,
      group: 'Adaptive workers',
    }),
  ],
});

const ROUTES = {
  'GET /api/platform': PLATFORM,
  'POST /api/dialog/folder': { path: 'D:\\Picked' },
  'GET /api/settings/general': () => GENERAL(),
  'GET /api/settings/search': SEARCH,
  'GET /api/settings/addons': ADDONS,
};

describe('Settings tabs', () => {
  it('follow the agreed order and names', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    const names = [
      'General',
      'Search',
      'Indexing',
      'Sources',
      'Cloud OCR',
      'Results',
      'Logs and database',
      'Add-ons',
    ];
    const tabs = names.map((name) => screen.getAllByRole('tab', { name }).at(-1));
    tabs.slice(1).forEach((tab, index) => {
      expect(
        tabs[index].compareDocumentPosition(tab) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });
  });
});

describe('Settings > grouping', () => {
  it('puts a heading over each run of related settings', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['Appearance', 'Languages', 'Data', 'Privacy']);
  });

  it('shows a note under a group heading and one heading per group', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/search' });
    await screen.findByTestId('setting-search.engine');
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['Searching', 'How text is matched', 'Similar (fuzzy) engine']);
    expect(screen.getByText('What counts as the same character in a search.')).toBeInTheDocument();
  });

  it('saves a free-text engine option when the field is left', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'PUT /api/settings/search/search.option.fuzzy.threshold': (body) => ({
        ...SEARCH().settings[2],
        value: body.value,
        is_default: false,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/search' });
    const field = await screen.findByRole('textbox', { name: 'Threshold' });
    await userEvent.clear(field);
    await userEvent.type(field, 'loose');
    await userEvent.tab();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/search/search.option.fuzzy.threshold',
        expect.objectContaining({ body: '{"value":"loose"}' }),
      ),
    );
  });
});

describe('Settings > folders', () => {
  const FOLDER_PUT = 'PUT /api/settings/general/location.data';

  it('shows the current folder and does not change it until confirmed', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByTestId('path-location.data')).toHaveTextContent(
      'C:\\Users\\me\\AppData\\Local\\VethuQ',
    );
    await screen.findByTestId('setting-metrics.opt_in'); // the whole section has loaded
    await userEvent.click(
      within(screen.getByTestId('setting-location.data')).getByRole('button', { name: /Change/ }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.clear(await within(dialog).findByRole('textbox', { name: 'Folder' }));
    await userEvent.type(
      await within(dialog).findByRole('textbox', { name: 'Folder' }),
      'D:\\Data',
    );
    expect(
      fetchMock.mock.calls.some(
        ([path, init]) => path.includes('location') && init?.method === 'PUT',
      ),
    ).toBe(false);
  });

  it('moves the data along by default, and says so', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      [FOLDER_PUT]: (body) => ({
        ...GENERAL().settings[1],
        value: body.value,
        is_default: false,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(
      within(await screen.findByTestId('setting-location.data')).getByRole('button', {
        name: /Change/,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('checkbox', { name: /Move my existing data/ })).toBeChecked();
    await userEvent.clear(await within(dialog).findByRole('textbox', { name: 'Folder' }));
    await userEvent.type(
      await within(dialog).findByRole('textbox', { name: 'Folder' }),
      'D:\\Data',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Change folder' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/general/location.data',
        expect.objectContaining({ body: '{"value":"D:\\\\Data","options":{"move":true}}' }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('path-location.data')).toHaveTextContent('D:\\Data');
  });

  it('can leave the existing data where it is', async () => {
    const fetchMock = mockApi({ ...ROUTES, [FOLDER_PUT]: () => GENERAL().settings[1] });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(
      within(await screen.findByTestId('setting-location.data')).getByRole('button', {
        name: /Change/,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /Move my existing data/ }));
    await userEvent.clear(await within(dialog).findByRole('textbox', { name: 'Folder' }));
    await userEvent.type(
      await within(dialog).findByRole('textbox', { name: 'Folder' }),
      'D:\\Data',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Change folder' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/general/location.data',
        expect.objectContaining({ body: expect.stringContaining('"move":false') }),
      ),
    );
  });

  it('keeps the dialog open and shows why the service refused', async () => {
    mockApi({
      ...ROUTES,
      [FOLDER_PUT]: new Response(
        JSON.stringify({ error: 'Indexing is running. Stop it before moving the data folder.' }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(
      within(await screen.findByTestId('setting-location.data')).getByRole('button', {
        name: /Change/,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.clear(await within(dialog).findByRole('textbox', { name: 'Folder' }));
    await userEvent.type(
      await within(dialog).findByRole('textbox', { name: 'Folder' }),
      'D:\\Data',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Change folder' }));
    expect(await within(dialog).findByText(/Indexing is running/)).toBeInTheDocument();
    expect(screen.getByTestId('path-location.data')).toHaveTextContent(
      'C:\\Users\\me\\AppData\\Local\\VethuQ',
    );
  });

  it('starts with the system folder picker, then confirms the folder it returned', async () => {
    const fetchMock = mockApi({ ...ROUTES, 'POST /api/dialog/folder': { path: 'E:\\Picked' } });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    await userEvent.click(
      within(screen.getByTestId('setting-location.backups')).getByRole('button', {
        name: /Change/,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('textbox', { name: 'Folder' })).toHaveValue('E:\\Picked');
    // The picker started at the folder in use.
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/dialog/folder',
      expect.objectContaining({
        body: JSON.stringify({ start: 'C:\\Users\\me\\AppData\\Local\\VethuQ\\db\\backups' }),
      }),
    );
    // Nothing is saved until the dialog is confirmed.
    expect(
      fetchMock.mock.calls.some(
        ([path, init]) => path.includes('location') && init?.method === 'PUT',
      ),
    ).toBe(false);
    expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('offers to move the data for the data folder the picker chose', async () => {
    mockApi({ ...ROUTES, 'POST /api/dialog/folder': { path: 'E:\\Picked' } });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    await userEvent.click(
      within(screen.getByTestId('setting-location.data')).getByRole('button', { name: /Change/ }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('textbox', { name: 'Folder' })).toHaveValue('E:\\Picked');
    expect(within(dialog).getByRole('checkbox', { name: /Move my existing data/ })).toBeChecked();
  });

  it('changes nothing when the picker is cancelled', async () => {
    const fetchMock = mockApi({ ...ROUTES, 'POST /api/dialog/folder': { path: null } });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    await userEvent.click(
      within(screen.getByTestId('setting-location.data')).getByRole('button', { name: /Change/ }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/dialog/folder', expect.anything()),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([path, init]) => path.includes('location') && init?.method === 'PUT',
      ),
    ).toBe(false);
    await waitFor(() =>
      expect(
        within(screen.getByTestId('setting-location.data')).getByRole('button', { name: /Change/ }),
      ).toBeEnabled(),
    );
  });

  it('falls back to typing the folder when the picker fails', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/dialog/folder': new Response('{}', { status: 500 }),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    await userEvent.click(
      within(screen.getByTestId('setting-location.data')).getByRole('button', { name: /Change/ }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('textbox', { name: 'Folder' })).toHaveValue(
      'C:\\Users\\me\\AppData\\Local\\VethuQ',
    );
  });

  it('opens the dialog at once, with the folder to type, on a host without a picker', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/platform': { kind: 'web', window_controls: false, folder_dialog: false },
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByTestId('setting-metrics.opt_in');
    await userEvent.click(
      within(screen.getByTestId('setting-location.backups')).getByRole('button', {
        name: /Change/,
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(fetchMock).not.toHaveBeenCalledWith('/api/dialog/folder', expect.anything());
    expect(within(dialog).queryByRole('button', { name: 'Browse…' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('textbox', { name: 'Folder' })).toHaveValue(
      'C:\\Users\\me\\AppData\\Local\\VethuQ\\db\\backups',
    );
  });

  it('is locked, with the reason, when an environment variable sets the data folder', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/settings/general': () =>
        GENERAL({
          data: {
            locked: 'The VETHUQ_HOME environment variable sets this folder; change it there.',
          },
        }),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    const row = await screen.findByTestId('setting-location.data');
    expect(within(row).getByText(/VETHUQ_HOME environment variable/)).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /Change/ })).toBeDisabled();
    expect(within(row).getByRole('button', { name: 'Use the default folder' })).toBeDisabled();
  });

  it('goes back to the default folder, moving the data back when asked', async () => {
    const custom = { value: 'D:\\Data', is_default: false };
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/settings/general': () => GENERAL({ data: custom }),
      'DELETE /api/settings/general/location.data': () => GENERAL().settings[1],
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(
      within(await screen.findByTestId('setting-location.data')).getByRole('button', {
        name: 'Use the default folder',
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('textbox', { name: 'Folder' })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Use the default folder' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/general/location.data',
        expect.objectContaining({ method: 'DELETE', body: '{"options":{"move":true}}' }),
      ),
    );
  });
});

describe('Settings > Add-ons', () => {
  it('shows one panel per add-on and hides reset where there is none', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/addons' });
    await screen.findByTestId('setting-backup.enabled');
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['Database backups (licensed)', 'Adaptive workers']);
    expect(screen.getByRole('switch', { name: 'Enabled' })).toBeChecked();
    expect(screen.getByText('12 hours')).toBeInTheDocument();
    const note = screen.getByTestId('setting-autoscale.note');
    expect(within(note).queryByRole('button', { name: /Reset/ })).not.toBeInTheDocument();
  });

  it('writes a change to the add-on setting', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'PUT /api/settings/addons/backup.enabled': (body) => ({
        ...ADDONS().settings[0],
        value: body.value,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/addons' });
    await userEvent.click(await screen.findByRole('switch', { name: 'Enabled' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/addons/backup.enabled',
        expect.objectContaining({ body: '{"value":false}' }),
      ),
    );
  });

  it('says so when no add-on has settings', async () => {
    mockApi({ ...ROUTES, 'GET /api/settings/addons': { section: 'addons', settings: [] } });
    renderWithProviders(<App />, { route: '/settings/addons' });
    expect(
      await screen.findByText('None of the installed add-ons has settings.'),
    ).toBeInTheDocument();
  });
});
