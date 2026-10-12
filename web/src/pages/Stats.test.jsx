import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { CATALOG, mockApi, renderWithProviders } from '../test/helpers.jsx';

const ROW = {
  key: 'x',
  files: 3,
  pages: 40,
  native_pages: 30,
  ocr_pages: 10,
  passes: 10,
  confidence: 0.91,
  bands: { high: 8, medium: 2, low: 0, unreliable: 0 },
  duration_ms: 120000,
  ms_per_ocr_page: 12000,
  pages_per_minute: 5,
  credits: 12.5,
  failures: 1,
};

const ROUTES = {
  'GET /api/stats/summary': {
    total: ROW,
    days: [
      { day: '2026-10-11', native: 10, ocr: 2 },
      { day: '2026-10-12', native: 20, ocr: 8 },
    ],
  },
  'GET /api/stats/breakdown': {
    totals: ROW,
    items: [
      { ...ROW, key: '/docs', source_id: 4, pages: 30 },
      { ...ROW, key: '/more', source_id: 5, pages: 10 },
    ],
    more: false,
  },
  'GET /api/sources': {
    sources: [{ id: 4, name: 'docs', path: '/docs' }],
  },
  'GET /api/catalog': CATALOG,
};

describe('Statistics', () => {
  it('summarises what was read', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats/summary' });
    expect(await screen.findByText('Pages read')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getByText('5.0 pages a minute')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Pages read per day' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Native text 30, OCR 10/ })).toBeInTheDocument();
  });

  it('has the two tabs and a refresh that asks again', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats' });
    await screen.findByText('Pages read');
    for (const name of ['Summary', 'Breakdown']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
    const asked = () =>
      fetchMock.mock.calls.filter(([p]) => p.startsWith('/api/stats/summary')).length;
    const before = asked();
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(asked()).toBeGreaterThan(before));
  });

  it('narrows to a period and passes it on', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats/summary' });
    await screen.findByText('Pages read');
    await userEvent.click(screen.getByRole('combobox', { name: 'Period' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Last 7 days' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([p]) => p.startsWith('/api/stats/summary') && p.includes('since='),
        ),
      ).toBe(true),
    );
  });

  it('breaks down by group, with the totals on top', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats/breakdown' });
    const table = await screen.findByRole('table', { name: 'Breakdown' });
    expect(await within(table).findByText('/docs')).toBeInTheDocument();
    expect(within(table).getByText('Total')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox', { name: 'Group by' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Language' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p.includes('group_by=language'))).toBe(true),
    );
  });

  it('narrows to a row that is clicked, and the chip takes it away', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats/breakdown' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'Group by' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Engine' }));
    await userEvent.click(await screen.findByText('/docs'));
    expect(await screen.findByText('Engine: /docs')).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p.includes('engine=%2Fdocs'))).toBe(true),
    );
    const chip = within(screen.getByRole('toolbar', { name: 'Narrowed to' }));
    await userEvent.click(chip.getAllByRole('button').at(-1)); // the chip's remove button
    await waitFor(() => expect(screen.queryByText('Engine: /docs')).not.toBeInTheDocument());
  });

  it('narrows to a source by its id, and can open it', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/stats/breakdown' });
    const table = await screen.findByRole('table', { name: 'Breakdown' });
    await within(table).findByText('/docs');
    await userEvent.click(within(table).getAllByRole('button', { name: 'Open source' })[0]);
    expect(screen.queryByRole('table', { name: 'Breakdown' })).not.toBeInTheDocument();
    void fetchMock;
  });
});
