import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const WALLET = {
  wallet: 'local',
  daily: 420,
  promotional: 0,
  one_off: 50,
  grace: 25,
  total: 495,
  daily_allowance: 500,
  daily_used: 80,
  bonus_active: true,
  bonus: 50,
  next_reset: '2026-10-13T00:00:00+00:00',
};

const SUMMARY = {
  wallets: [{ wallet: 'local', daily: 420, daily_allowance: 500, total: 495 }],
  primary: 'local',
  daily: 420,
  daily_allowance: 500,
  total: 495,
  level: 'ok',
  next_reset: '2026-10-13T00:00:00+00:00',
};

const GRANT = {
  id: 1,
  wallet: 'local',
  kind: 'one_off',
  name: 'Starter',
  origin: 'starter',
  scope: null,
  amount: 100,
  remaining: 50,
  used: 50,
  granted_at: '2026-10-01T00:00:00+00:00',
  expires_at: null,
  expired: false,
};

const ROUTES = {
  'GET /api/credits/summary': SUMMARY,
  'GET /api/credits/wallets': {
    wallets: [WALLET],
    totals: [{ wallet: 'local', received: 600, consumed: 105, lapsed: 0, remaining: 495 }],
  },
  'GET /api/credits/grants': { total: 1, items: [GRANT] },
  'GET /api/credits/daily': {
    wallets: ['local'],
    days: [
      { day: '2026-10-11', local: 10 },
      { day: '2026-10-12', local: 80 },
    ],
  },
  'GET /api/credits/usage': {
    total: 1,
    credits: 12,
    pages: 12,
    items: [
      {
        key: '1',
        source_id: 1,
        name: 'docs',
        path: '/docs',
        source: 'docs',
        credits: 12,
        pages: 12,
        last_at: null,
      },
    ],
  },
  'GET /api/credits/ledger': {
    items: [
      {
        id: 5,
        at: '2026-10-12T10:00:00+00:00',
        wallet: 'local',
        kind: 'charge',
        amount: 1,
        file: '/docs/a.pdf',
        page_number: 3,
        phase: 'quick',
        language: 'en',
        run_id: 2,
        note: '/docs/a.pdf',
      },
    ],
    more: false,
  },
  'GET /api/sources': { sources: [] },
};

describe('Credits', () => {
  it('shows what is left today in the status bar and opens the page from it', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/' });
    const item = await screen.findByTestId('credits-status');
    expect(item).toHaveTextContent('420 credits left today');
    await userEvent.click(item);
    expect(await screen.findByText('Today’s allowance'.replace('’', "'"))).toBeInTheDocument();
  });

  it('warns in words when the day is used up', async () => {
    mockApi({ ...ROUTES, 'GET /api/credits/summary': { ...SUMMARY, daily: 0, level: 'empty' } });
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByTestId('credits-status')).toHaveTextContent("Today's credits used");
  });

  it('has no credits item when there is no wallet', async () => {
    mockApi({});
    renderWithProviders(<App />, { route: '/' });
    await screen.findByTestId('status-bar');
    expect(screen.queryByTestId('credits-status')).not.toBeInTheDocument();
  });

  it('shows the totals on the overview', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/credits/overview' });
    expect(await screen.findByText('420 left of 500')).toBeInTheDocument();
    expect(screen.getByText(/80 used today, including 50 for sharing metrics/)).toBeInTheDocument();
    expect(screen.getByText('Consumed')).toBeInTheDocument();
    expect(screen.getByText('105')).toBeInTheDocument();
  });

  it('lists the credits held with their kind and what is left', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/credits/grants' });
    const table = await screen.findByRole('table', { name: 'Grants' });
    expect(await within(table).findByText('Starter')).toBeInTheDocument();
    expect(within(table).getByText('One-off')).toBeInTheDocument();
    expect(within(table).getByText('Never')).toBeInTheDocument();
    await userEvent.click(within(table).getByText('Amount'));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path.includes('sort=amount&order=desc'))).toBe(
        true,
      ),
    );
  });

  it('draws the days as a chart and a table', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/credits/daily' });
    expect(await screen.findByRole('img', { name: 'Credits spent per day' })).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Credits per day' });
    expect(within(table).getAllByText('80').length).toBe(2);
  });

  it('drills from a source to its files', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/credits/usage' });
    await userEvent.click(await screen.findByText('docs'));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path.includes('group_by=file&source=1'))).toBe(
        true,
      ),
    );
    expect(await screen.findByRole('table', { name: 'Credits per file' })).toBeInTheDocument();
  });

  it('shows the ledger with spending as a minus', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/credits/ledger' });
    const table = await screen.findByRole('table', { name: 'Ledger' });
    expect(await within(table).findByText('-1')).toBeInTheDocument();
    expect(within(table).getByText('/docs/a.pdf')).toBeInTheDocument();
  });

  it('redeems a licence and says what was added', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'POST /api/credits/redeem': { redeemed: [{ id: 'g1', credits: 200, added: true }] },
    });
    renderWithProviders(<App />, { route: '/credits/overview' });
    await userEvent.click(await screen.findByRole('button', { name: 'Redeem a licence' }));
    await userEvent.type(await screen.findByPlaceholderText('Paste the licence text'), 'token');
    await userEvent.click(screen.getByRole('button', { name: 'Redeem' }));
    expect(await screen.findByText('Added 200 credits (g1).')).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([path]) => path === '/api/credits/redeem');
    expect(JSON.parse(call[1].body)).toEqual({ token: 'token' });
  });

  it('says why a licence was refused', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/credits/redeem': new Response(
        JSON.stringify({ error: 'The licence is not valid.' }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/credits/overview' });
    await userEvent.click(await screen.findByRole('button', { name: 'Redeem a licence' }));
    await userEvent.type(await screen.findByPlaceholderText('Paste the licence text'), 'bad');
    await userEvent.click(screen.getByRole('button', { name: 'Redeem' }));
    expect(await screen.findByText('The licence is not valid.')).toBeInTheDocument();
  });
});
