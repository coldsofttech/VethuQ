import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const FILES = {
  components: [
    {
      component: 'cli',
      description: 'The command line.',
      exists: true,
      size_bytes: 2048,
      days: ['2026-10-11', '2026-10-12'],
    },
    { component: 'index', description: 'The indexer.', exists: false, size_bytes: null, days: [] },
  ],
};

const entry = (message, level = 'info', time = '10:00:01') => ({
  timestamp: `2026-10-12T${time}`,
  level,
  thread: 'main',
  logger: 'vethuq.cli',
  message,
  raw: message,
});

const ENTRIES = {
  total: 2,
  offset: 0,
  exists: true,
  items: [
    entry('started up'),
    entry('it broke\nTraceback (most recent call last)', 'error', '10:00:05'),
  ],
};

const ROUTES = { 'GET /api/logs': FILES, 'GET /api/logs/cli': ENTRIES };

afterEach(() => vi.useRealTimers());

describe('Logs', () => {
  it('is its own menu item and shows the entries with their level and traceback', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/logs' });
    const box = await screen.findByRole('log', { name: 'Log entries' });
    expect(await within(box).findByText('started up')).toBeInTheDocument();
    expect(within(box).getByText(/Traceback \(most recent call last\)/)).toBeInTheDocument();
    expect(within(box).getByText('error')).toBeInTheDocument();
    expect(screen.getByText('2 entries')).toBeInTheDocument();
    expect(screen.getByText('The command line.')).toBeInTheDocument();
    expect(screen.getAllByRole('tab', { name: 'Logs' })[0]).toBeInTheDocument();
  });

  it('asks again with the level, the search text and the day', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/logs' });
    await screen.findByText('started up');
    await userEvent.click(screen.getByRole('combobox', { name: 'Level' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Errors only' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Search the messages' }), 'broke');
    await userEvent.click(screen.getByRole('combobox', { name: 'Day' }));
    await userEvent.click(await screen.findByRole('option', { name: '2026-10-11' }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([p]) =>
            p.includes('level=error') &&
            p.includes('contains=broke') &&
            p.includes('day=2026-10-11'),
        ),
      ).toBe(true),
    );
  });

  it('says so when a log has no file yet', async () => {
    mockApi({
      ...ROUTES,
      'GET /api/logs/index': { total: 0, offset: 0, items: [], exists: false },
    });
    renderWithProviders(<App />, { route: '/logs' });
    await screen.findByText('started up');
    await userEvent.click(screen.getByRole('combobox', { name: 'Log' }));
    await userEvent.click(await screen.findByRole('option', { name: 'index (empty)' }));
    expect(await screen.findByText('There is no log for this day yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export what is shown' })).toBeDisabled();
  });

  it('follows: asks for what came after and adds it', async () => {
    const fetchMock = mockApi({
      ...ROUTES,
      'GET /api/logs/cli?order=asc&limit=500&after=2': {
        total: 3,
        offset: 2,
        exists: true,
        items: [entry('a new line', 'info', '10:00:09')],
      },
    });
    renderWithProviders(<App />, { route: '/logs' });
    await screen.findByText('started up');
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await userEvent.click(screen.getByRole('button', { name: 'Follow new entries' }));
    expect(screen.getByRole('switch', { name: 'Newest first' })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    const asked = fetchMock.mock.calls.map(([p]) => p).filter((p) => p.includes('after='));
    expect(asked.length).toBeGreaterThan(0);
    expect(await screen.findByText('a new line')).toBeInTheDocument();
    expect(screen.getByText(/3 entries · following/)).toBeInTheDocument();
  });
});
