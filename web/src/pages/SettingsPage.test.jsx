import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { humanMinutes } from '../components/SettingRow.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const WORKERS_OPTIONS = [
  { value: 'auto', label: 'Automatic (sized to this computer)', available: true, reason: '' },
  { value: 0, label: '0: one file at a time', available: true, reason: '' },
  { value: 4, label: '4', available: true, reason: '' },
];
const DEPTH_OPTIONS = [
  { value: 'quick', label: 'Quick: upright text', available: true, reason: '' },
  {
    value: 'moderate',
    label: 'Moderate: also rotated pages',
    available: false,
    reason: 'Needs the vethuq-addon-ocr-moderate add-on.',
  },
];

function indexing() {
  return [
    {
      id: 'index.workers',
      label: 'Files indexed at once',
      description: 'How many files are read in parallel.',
      type: 'choice',
      value: 'auto',
      default: 'auto',
      is_default: true,
      advanced: false,
      note: 'Applies from the next indexing run.',
      options: WORKERS_OPTIONS,
    },
    {
      id: 'index.retry_attempts',
      label: 'Retries for a failed file',
      description: 'How many times a failed file is tried again.',
      type: 'integer',
      value: 3,
      default: 3,
      is_default: true,
      advanced: false,
      note: '',
      min: 0,
    },
    {
      id: 'ocr.engine',
      label: 'OCR depth',
      description: 'How far indexing reads.',
      type: 'choice',
      value: 'quick',
      default: 'quick',
      is_default: true,
      advanced: false,
      note: '',
      options: DEPTH_OPTIONS,
    },
    {
      id: 'ocr.gpu',
      label: 'Use the graphics card for OCR',
      description: 'Ask OCR engines to use the GPU.',
      type: 'boolean',
      value: false,
      default: false,
      is_default: true,
      advanced: false,
      note: '',
    },
    {
      id: 'index.stability_check_seconds',
      label: 'Wait for files to stop changing',
      description: 'How long a run waits.',
      type: 'number',
      value: 1,
      default: 1,
      is_default: true,
      advanced: true,
      note: '',
      min: 0,
      unit: 'seconds',
    },
  ];
}

const BASE = {
  'GET /api/platform': { kind: 'web', window_controls: false },
  'GET /api/settings/indexing': () => ({ section: 'indexing', settings: indexing() }),
};

async function openIndexing() {
  renderWithProviders(<App />, { route: '/settings/indexing' });
  return screen.findByTestId('setting-index.workers');
}

describe('Settings > Indexing', () => {
  it('lists the basic settings with their values and hides the advanced ones', async () => {
    mockApi(BASE);
    await openIndexing();
    expect(screen.getByText('Retries for a failed file')).toBeInTheDocument();
    expect(screen.getByText('OCR depth')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Files indexed at once' })).toHaveValue(
      'Automatic (sized to this computer)',
    );
    expect(screen.queryByText('Wait for files to stop changing')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('switch', { name: 'Show advanced settings' }));
    expect(screen.getByText('Wait for files to stop changing')).toBeInTheDocument();
  });

  it('saves a typed number when the field is left, and not while it is being typed', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'PUT /api/settings/indexing/index.retry_attempts': (body) => ({
        ...indexing()[1],
        value: body.value,
        is_default: false,
      }),
    });
    await openIndexing();
    const field = screen.getByRole('spinbutton', { name: 'Retries for a failed file' });
    await userEvent.clear(field);
    await userEvent.type(field, '7');
    const saved = () =>
      fetchMock.mock.calls.filter(
        ([path, init]) => path.endsWith('retry_attempts') && init?.method === 'PUT',
      );
    expect(saved()).toHaveLength(0);

    await userEvent.tab();
    await waitFor(() => expect(saved()).toHaveLength(1));
    expect(saved()[0][1].body).toBe('{"value":7}');
  });

  it('saves a stepped number at once', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'PUT /api/settings/indexing/index.retry_attempts': (body) => ({
        ...indexing()[1],
        value: body.value,
        is_default: false,
      }),
    });
    await openIndexing();
    const field = screen.getByRole('spinbutton', { name: 'Retries for a failed file' });
    await userEvent.click(field);
    await userEvent.keyboard('{ArrowUp}');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/indexing/index.retry_attempts',
        expect.objectContaining({ body: '{"value":4}' }),
      ),
    );
  });

  it('saves a switch change and shows the new value', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'PUT /api/settings/indexing/ocr.gpu': (body) => ({
        ...indexing()[3],
        value: body.value,
        is_default: false,
      }),
    });
    await openIndexing();
    await userEvent.click(screen.getByRole('switch', { name: 'Use the graphics card for OCR' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/indexing/ocr.gpu',
        expect.objectContaining({ method: 'PUT', body: '{"value":true}' }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Use the graphics card for OCR' })).toBeChecked(),
    );
  });

  it('sends a typed value for a choice, such as the number 4 for the workers', async () => {
    const fetchMock = mockApi({
      ...BASE,
      'PUT /api/settings/indexing/index.workers': (body) => ({
        ...indexing()[0],
        value: body.value,
        is_default: false,
      }),
    });
    await openIndexing();
    await userEvent.click(screen.getByRole('combobox', { name: 'Files indexed at once' }));
    await userEvent.click(await screen.findByRole('option', { name: '4' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/indexing/index.workers',
        expect.objectContaining({ body: '{"value":4}' }),
      ),
    );
  });

  it('shows why a change was refused and puts the old value back', async () => {
    mockApi({
      ...BASE,
      'PUT /api/settings/indexing/ocr.gpu': new Response(
        JSON.stringify({ error: 'Use true or false.' }),
        { status: 422 },
      ),
    });
    await openIndexing();
    await userEvent.click(screen.getByRole('switch', { name: 'Use the graphics card for OCR' }));
    expect(await screen.findByText('Use true or false.')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Use the graphics card for OCR' })).not.toBeChecked();
  });

  it('offers reset only for a changed setting, and resets it', async () => {
    const changed = indexing();
    changed[1] = { ...changed[1], value: 5, is_default: false };
    const fetchMock = mockApi({
      ...BASE,
      'GET /api/settings/indexing': () => ({ section: 'indexing', settings: changed }),
      'DELETE /api/settings/indexing/index.retry_attempts': () => indexing()[1],
    });
    await openIndexing();

    const row = screen.getByTestId('setting-index.retry_attempts');
    const reset = within(row).getByRole('button', { name: /Reset to default/ });
    expect(reset).toBeEnabled();
    expect(
      within(screen.getByTestId('setting-ocr.gpu')).getByRole('button', {
        name: /Reset to default/,
      }),
    ).toBeDisabled();

    await userEvent.click(reset);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/indexing/index.retry_attempts',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
    await waitFor(() => expect(reset).toBeDisabled());
  });

  it('lists an unavailable OCR depth as disabled with the reason', async () => {
    mockApi(BASE);
    await openIndexing();
    await userEvent.click(screen.getByRole('combobox', { name: 'OCR depth' }));
    const option = await screen.findByRole('option', { name: /Moderate/ });
    expect(option).toHaveAttribute('aria-disabled', 'true');
    expect(option).toHaveTextContent('Needs the vethuq-addon-ocr-moderate add-on.');
  });

  it('switches between the General and Indexing sections', async () => {
    mockApi(BASE);
    renderWithProviders(<App />, { route: '/settings' });
    expect(await screen.findByText('Use my system setting')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Indexing' }));
    expect(await screen.findByTestId('setting-index.workers')).toBeInTheDocument();
  });
});

const setting = (overrides) => ({
  description: 'A description.',
  is_default: true,
  advanced: false,
  note: '',
  ...overrides,
});

const LANGUAGES = [
  { value: 'en', label: 'English', available: true, reason: '' },
  { value: 'te', label: 'Telugu', available: true, reason: '' },
  { value: 'fr', label: 'French', available: false, reason: 'This language is turned off.' },
];

const GENERAL = () => ({
  section: 'general',
  settings: [
    setting({
      id: 'languages.languages',
      label: 'Languages to read documents in',
      type: 'multichoice',
      value: ['en'],
      default: ['en'],
      options: LANGUAGES,
      min: 1,
    }),
    setting({
      id: 'updates.check',
      label: 'Check for updates',
      type: 'choice',
      value: 'on',
      default: 'on',
      options: [
        { value: 'on', label: 'On: check and offer to update', available: true, reason: '' },
        { value: 'notify-only', label: 'Notify only', available: true, reason: '' },
        { value: 'off', label: 'Off: never check', available: true, reason: '' },
      ],
      note: 'The VETHUQ_UPDATE_CHECK environment variable switches update checks off.',
    }),
    setting({
      id: 'metrics.opt_in',
      label: 'Share anonymous usage metrics',
      type: 'boolean',
      value: false,
      default: false,
    }),
    setting({
      id: 'updates.skipped_version',
      label: 'Skipped update',
      type: 'text',
      value: '9.9.9',
      default: null,
      is_default: false,
      readonly: true,
      advanced: true,
    }),
    setting({
      id: 'updates.snoozed_until',
      label: 'Update notice snoozed until',
      type: 'text',
      value: null,
      default: null,
      readonly: true,
      advanced: true,
    }),
  ],
});

const SYSTEM = () => ({
  section: 'system',
  settings: [
    setting({
      id: 'logs.level',
      label: 'Log detail',
      type: 'choice',
      value: 'info',
      default: 'info',
      options: [
        { value: 'debug', label: 'Debug: everything', available: true, reason: '' },
        { value: 'info', label: 'Info: normal activity', available: true, reason: '' },
      ],
      note: 'Takes effect at once.',
    }),
    setting({
      id: 'logs.retention_days',
      label: 'Keep log files for',
      type: 'integer',
      value: 15,
      default: 15,
      min: 1,
      unit: 'days',
    }),
    setting({
      id: 'database.integrity_check_interval_minutes',
      label: 'Time between automatic checks',
      type: 'integer',
      value: 1440,
      default: 1440,
      min: 1,
      unit: 'minutes',
      advanced: true,
    }),
  ],
});

const SOURCES = () => ({
  section: 'sources',
  settings: [
    setting({
      id: 'sources.removed_retention_minutes',
      label: 'Keep a removed source for',
      type: 'integer',
      value: 10080,
      default: 10080,
      min: 0,
      unit: 'minutes',
    }),
  ],
});

const TIERS = () => ({
  section: 'tiers',
  settings: [
    setting({
      id: 'tiers.default',
      label: 'Processing tier',
      type: 'choice',
      value: 'local',
      default: 'local',
      options: [
        { value: 'local', label: 'Local', available: true, reason: '' },
        { value: 'hybrid', label: 'Hybrid', available: false, reason: 'it needs the GitHub tier' },
      ],
    }),
    setting({
      id: 'tiers.phases',
      label: 'OCR phases sent to GitHub',
      type: 'multichoice',
      value: [],
      default: [],
      options: [
        { value: 'moderate', label: 'Moderate', available: true, reason: '' },
        { value: 'deep', label: 'Deep', available: true, reason: '' },
      ],
    }),
    setting({
      id: 'tiers.max_job_pages',
      label: 'Most pages in one remote job',
      type: 'integer',
      value: 200,
      default: 200,
      min: 1,
      advanced: true,
    }),
  ],
});

const RESULTS = () => ({
  section: 'results',
  settings: [
    setting({
      id: 'confidence.bands',
      label: 'Confidence bands',
      type: 'bands',
      value: [70, 80, 90],
      default: [70, 80, 90],
      labels: ['Low from', 'Medium from', 'High from'],
      min: 0,
      max: 100,
      unit: '%',
    }),
  ],
});

const MORE = {
  ...BASE,
  'GET /api/settings/general': GENERAL,
  'GET /api/settings/sources': SOURCES,
  'GET /api/settings/tiers': TIERS,
  'GET /api/settings/results': RESULTS,
  'GET /api/settings/system': SYSTEM,
};

describe('humanMinutes', () => {
  it('reads minutes the way a person would', () => {
    expect(humanMinutes(10080)).toBe('7 days');
    expect(humanMinutes(1440)).toBe('1 day');
    expect(humanMinutes(90)).toBe('90 minutes');
    expect(humanMinutes(120)).toBe('2 hours');
    expect(humanMinutes(0)).toBe('immediately');
  });
});

describe('Settings > General', () => {
  it('shows the theme above the languages and the metrics choice', async () => {
    mockApi(MORE);
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByTestId('setting-theme')).toBeInTheDocument();
    expect(await screen.findByTestId('setting-languages.languages')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Share anonymous usage metrics' })).not.toBeChecked();
  });

  it('chooses several languages and sends them as a list', async () => {
    const fetchMock = mockApi({
      ...MORE,
      'PUT /api/settings/general/languages.languages': (body) => ({
        ...GENERAL().settings[0],
        value: body.value,
        is_default: false,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await userEvent.click(
      await screen.findByRole('combobox', { name: 'Languages to read documents in' }),
    );
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Telugu' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/general/languages.languages',
        expect.objectContaining({ body: '{"value":["en","te"]}' }),
      ),
    );
    const french = await screen.findByRole('menuitemcheckbox', { name: /French/ });
    expect(french).toHaveAttribute('aria-disabled', 'true');
    expect(french).toHaveTextContent('This language is turned off.');
  });
});

describe('Settings > Sources', () => {
  it('shows the retention in minutes with a readable duration', async () => {
    mockApi(MORE);
    renderWithProviders(<App />, { route: '/settings/sources' });
    expect(await screen.findByText('Keep a removed source for')).toBeInTheDocument();
    expect(screen.getByText('7 days')).toBeInTheDocument();
    expect(screen.getByText(/Unit: minutes/)).toBeInTheDocument();
  });
});

describe('Settings > Processing', () => {
  it('disables a tier that cannot be used and explains why', async () => {
    mockApi(MORE);
    renderWithProviders(<App />, { route: '/settings/tiers' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'Processing tier' }));
    const hybrid = await screen.findByRole('option', { name: /Hybrid/ });
    expect(hybrid).toHaveAttribute('aria-disabled', 'true');
    expect(hybrid).toHaveTextContent('it needs the GitHub tier');
  });

  it('lets none, one or both OCR phases be chosen, and hides the advanced limits', async () => {
    const fetchMock = mockApi({
      ...MORE,
      'PUT /api/settings/tiers/tiers.phases': (body) => ({
        ...TIERS().settings[1],
        value: body.value,
        is_default: false,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/tiers' });
    expect(screen.queryByText('Most pages in one remote job')).not.toBeInTheDocument();
    await userEvent.click(
      await screen.findByRole('combobox', { name: 'OCR phases sent to GitHub' }),
    );
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Deep' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/tiers/tiers.phases',
        expect.objectContaining({ body: '{"value":["deep"]}' }),
      ),
    );
    await userEvent.click(screen.getByRole('switch', { name: 'Show advanced settings' }));
    expect(screen.getByText('Most pages in one remote job')).toBeInTheDocument();
  });
});

describe('Settings > Results', () => {
  async function bands() {
    renderWithProviders(<App />, { route: '/settings/results' });
    return screen.findByRole('spinbutton', { name: 'Low from' });
  }

  async function type(name, text) {
    const field = screen.getByRole('spinbutton', { name });
    await userEvent.clear(field);
    await userEvent.type(field, text);
    await userEvent.tab();
  }

  it('shows the three bands and keeps Apply off until something changes', async () => {
    mockApi(MORE);
    await bands();
    expect(screen.getByRole('spinbutton', { name: 'Low from' })).toHaveValue('70');
    expect(screen.getByRole('spinbutton', { name: 'Medium from' })).toHaveValue('80');
    expect(screen.getByRole('spinbutton', { name: 'High from' })).toHaveValue('90');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });

  it('saves the bands together when Apply is pressed', async () => {
    const fetchMock = mockApi({
      ...MORE,
      'PUT /api/settings/results/confidence.bands': (body) => ({
        ...RESULTS().settings[0],
        value: body.value,
        is_default: false,
      }),
    });
    await bands();
    await type('Low from', '60');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/results/confidence.bands',
        expect.objectContaining({ body: '{"value":[60,80,90]}' }),
      ),
    );
  });

  it('refuses bands that do not rise, before asking the service', async () => {
    const fetchMock = mockApi(MORE);
    await bands();
    await type('Medium from', '95');
    expect(
      await screen.findByText(/Each band must start higher than the one before/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('confidence.bands'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});

describe('Settings > General > updates', () => {
  it('shows why the update check is off when the environment forces it', async () => {
    mockApi(MORE);
    renderWithProviders(<App />, { route: '/settings/general' });
    expect(await screen.findByText('Check for updates')).toBeInTheDocument();
    expect(screen.getByText(/VETHUQ_UPDATE_CHECK environment variable/)).toBeInTheDocument();
  });

  it('shows the skipped version read-only and clears it', async () => {
    const fetchMock = mockApi({
      ...MORE,
      'DELETE /api/settings/general/updates.skipped_version': () => ({
        ...GENERAL().settings[3],
        value: null,
        is_default: true,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/general' });
    await screen.findByText('Check for updates');
    expect(screen.queryByText('Skipped update')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'Show advanced settings' }));

    const row = screen.getByTestId('setting-updates.skipped_version');
    expect(within(row).getByText('9.9.9')).toBeInTheDocument();
    expect(within(row).queryByRole('combobox')).not.toBeInTheDocument();
    expect(within(row).queryByRole('spinbutton')).not.toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Clear: Skipped update' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/general/updates.skipped_version',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
    await waitFor(() => expect(within(row).getByText('None')).toBeInTheDocument());
    expect(within(row).getByRole('button', { name: 'Clear: Skipped update' })).toBeDisabled();
  });
});

describe('Settings > System', () => {
  it('lists the log and database settings and hides the advanced one', async () => {
    mockApi(MORE);
    renderWithProviders(<App />, { route: '/settings/system' });
    expect(await screen.findByText('Log detail')).toBeInTheDocument();
    expect(screen.getByText('Keep log files for')).toBeInTheDocument();
    expect(screen.queryByText('Time between automatic checks')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'Show advanced settings' }));
    const row = screen.getByTestId('setting-database.integrity_check_interval_minutes');
    expect(within(row).getByText('1 day')).toBeInTheDocument();
  });

  it('changes the log level', async () => {
    const fetchMock = mockApi({
      ...MORE,
      'PUT /api/settings/system/logs.level': (body) => ({
        ...SYSTEM().settings[0],
        value: body.value,
        is_default: false,
      }),
    });
    renderWithProviders(<App />, { route: '/settings/system' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'Log detail' }));
    await userEvent.click(await screen.findByRole('option', { name: /Debug/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/settings/system/logs.level',
        expect.objectContaining({ body: '{"value":"debug"}' }),
      ),
    );
  });
});
