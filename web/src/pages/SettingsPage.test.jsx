import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
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
