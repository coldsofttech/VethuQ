import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const STATE = {
  running: false,
  paused: false,
  finished: true,
  queued: 0,
  waiting_credits: [{ id: 7, resume_at: '2030-01-02T00:00:00+00:00' }],
  runner: { mode: 'service', service_running: true, one_off: null },
};

describe('Waiting for credits', () => {
  it('says that requests wait for credits and when they carry on', async () => {
    mockApi({ 'GET /api/index/state': STATE });
    renderWithProviders(<App />, { route: '/indexing/activity' });
    expect(await screen.findByText(/waiting for credits; the background service/i)).toBeTruthy();
  });

  it('gives the reason in the queue', async () => {
    mockApi({
      'GET /api/index/state': STATE,
      'GET /api/index/requests': {
        requests: [
          {
            id: 7,
            target: null,
            mode: 'run',
            status: 'waiting_credits',
            resume_at: '2030-01-02T00:00:00+00:00',
            reason: 'Waiting for credits until 2030-01-02T00:00:00+00:00',
            requested_at: '2030-01-01T09:00:00+00:00',
            open: false,
          },
        ],
      },
    });
    renderWithProviders(<App />, { route: '/indexing/queue' });
    expect(await screen.findByText(/Credits are back/)).toBeTruthy();
  });
});
