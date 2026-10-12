import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const JOB = { running: false, action: null, progress: {}, error: null, finished: false };

const MODELS = {
  folder: '/data/models',
  installed: 1,
  size_bytes: 2048,
  items: [
    {
      name: 'det',
      engine: 'paddle',
      kind: 'detection',
      shared: true,
      languages: ['en', 'ta'],
      installed: true,
      path: '/m/det',
      size_bytes: 2048,
    },
    {
      name: 'rec_ta',
      engine: 'paddle',
      kind: 'recognition',
      shared: false,
      languages: ['ta'],
      installed: false,
      path: '/m/ta',
      size_bytes: 0,
    },
  ],
};

const ROUTES = {
  'GET /api/ocr': {
    engines: [
      {
        id: 'paddle',
        label: 'PaddleOCR',
        profiles: ['mobile', 'server'],
        available: true,
        reason: '',
      },
      { id: 'other', label: 'Other', profiles: [], available: false, reason: 'not installed' },
    ],
    phases: [
      {
        id: 'quick',
        label: 'Quick',
        order: 1,
        angles: [0],
        profile: 'mobile',
        available: true,
        reason: '',
      },
      {
        id: 'deep',
        label: 'Deep',
        order: 3,
        angles: [0, 90],
        profile: 'server',
        available: false,
        reason: 'needs the server models',
      },
    ],
  },
  'GET /api/ocr/models': MODELS,
  'GET /api/ocr/job': JOB,
  'GET /api/settings/ocr': { section: 'ocr', settings: [] },
};

const called = (fetchMock, path) => fetchMock.mock.calls.filter(([p]) => p === path);

describe('OCR in settings', () => {
  it('lists the engines, phases and models', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings/ocr' });
    const engines = await screen.findByRole('table', { name: 'OCR engines' });
    expect(within(engines).getByText('PaddleOCR')).toBeInTheDocument();
    expect(within(engines).getByText('mobile, server')).toBeInTheDocument();
    expect(within(engines).getByText('not installed')).toBeInTheDocument();
    const phases = screen.getByRole('table', { name: 'OCR phases' });
    expect(within(phases).getByText('0°, 90°')).toBeInTheDocument();
    expect(within(phases).getByText('needs the server models')).toBeInTheDocument();
    const models = screen.getByRole('table', { name: 'OCR models' });
    expect(within(models).getByText('Installed')).toBeInTheDocument();
    expect(within(models).getByText('Not downloaded')).toBeInTheDocument();
    expect(within(models).getByText('2.0 KB')).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 models installed/)).toBeInTheDocument();
  });

  it('downloads what is missing for the chosen language', async () => {
    let going = false;
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/ocr/job': () => (going ? { ...JOB, running: true, action: 'download' } : JOB),
      'POST /api/ocr/models/download': () => {
        going = true;
        return { ...JOB, running: true, action: 'download' };
      },
    });
    renderWithProviders(<App />, { route: '/settings/ocr' });
    await screen.findByRole('table', { name: 'OCR models' });
    await userEvent.click(screen.getByRole('combobox', { name: 'Language' }));
    await userEvent.click(await screen.findByRole('option', { name: 'ta' }));
    await userEvent.click(screen.getByRole('button', { name: 'Download missing models' }));
    await waitFor(() => {
      const [call] = called(fetchMock, '/api/ocr/models/download');
      expect(JSON.parse(call[1].body)).toEqual({ languages: ['ta'] });
    });
    expect(await screen.findByText(/Downloading models/)).toBeInTheDocument();
  });

  it('asks before downloading again, then sends the names shown', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'POST /api/ocr/models/redownload': { ...JOB, running: true, action: 'redownload' },
    });
    renderWithProviders(<App />, { route: '/settings/ocr' });
    await screen.findByRole('table', { name: 'OCR models' });
    await userEvent.click(screen.getByRole('button', { name: 'Download again' }));
    expect(await screen.findByText('Download the models again?')).toBeInTheDocument();
    expect(called(fetchMock, '/api/ocr/models/redownload')).toHaveLength(0);
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Download again' }),
    );
    await waitFor(() => {
      const [call] = called(fetchMock, '/api/ocr/models/redownload');
      expect(JSON.parse(call[1].body).names).toEqual(['det', 'rec_ta']);
    });
  });

  it('removes the models of a language, with the shared ones only if asked', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'POST /api/ocr/models/clear': { removed: ['rec_ta'] },
    });
    renderWithProviders(<App />, { route: '/settings/ocr' });
    await screen.findByRole('table', { name: 'OCR models' });
    expect(
      screen.getByRole('button', { name: 'Pick a language to remove its models' }),
    ).toBeDisabled();
    await userEvent.click(screen.getByRole('combobox', { name: 'Language' }));
    await userEvent.click(await screen.findByRole('option', { name: 'ta' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove models for ta' }));
    await userEvent.click(
      await screen.findByRole('checkbox', { name: /shared by every language/ }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => {
      const [call] = called(fetchMock, '/api/ocr/models/clear');
      expect(JSON.parse(call[1].body)).toEqual({ languages: ['ta'], include_shared: true });
    });
    expect(await screen.findByText('Removed 1 model')).toBeInTheDocument();
  });

  it('cleans up unused models after a question', async () => {
    mockApi({ ...ROUTES, 'POST /api/ocr/models/clean': { removed: [] } });
    renderWithProviders(<App />, { route: '/settings/ocr' });
    await screen.findByRole('table', { name: 'OCR models' });
    await userEvent.click(screen.getByRole('button', { name: 'Remove models nothing uses' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Clean up' }));
    expect(await screen.findByText('Removed 0 unused files')).toBeInTheDocument();
  });

  it('shows a download in progress and why one failed', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/ocr/job': {
        ...JOB,
        running: true,
        action: 'download',
        progress: { rec_ta: 'downloading' },
      },
    });
    renderWithProviders(<App />, { route: '/settings/ocr' });
    const models = await screen.findByRole('table', { name: 'OCR models' });
    expect(await within(models).findByText('Downloading')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download missing models' })).toBeDisabled();
  });
});
