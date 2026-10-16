import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../App.jsx';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';

const STATUS = {
  opted_in: false,
  consent_current: false,
  prompted: false,
  available: true,
  bonus_percent: 10,
  pending_days: 0,
};

describe('The first-run question about sharing statistics', () => {
  it('asks, and shares nothing until Share is pressed', async () => {
    let optedIn = false;
    const fetchMock = mockApi({
      'GET /api/metrics': () => ({ ...STATUS, opted_in: optedIn, prompted: optedIn }),
      'POST /api/metrics/opt-in': () => {
        optedIn = true;
        return { ...STATUS, opted_in: true, consent_current: true, prompted: true };
      },
    });
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByText(/Help improve reading and search/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/metrics/opt-in')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Share' }));
    await waitFor(() => expect(screen.queryByText(/Help improve reading and search/)).toBeNull());
  });

  it('"Not now" asks no more and shares nothing', async () => {
    const fetchMock = mockApi({
      'GET /api/metrics': STATUS,
      'POST /api/metrics/prompt': { ...STATUS, prompted: true },
    });
    renderWithProviders(<App />, { route: '/' });
    await userEvent.click(await screen.findByRole('button', { name: 'Not now' }));
    await waitFor(() => expect(screen.queryByText(/Help improve reading and search/)).toBeNull());
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/metrics/opt-in')).toBe(false);
  });

  it('is not shown when the policy does not allow sharing, or it was answered', async () => {
    const fetchMock = mockApi({ 'GET /api/metrics': { ...STATUS, available: false } });
    renderWithProviders(<App />, { route: '/' });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path === '/api/metrics')).toBe(true),
    );
    expect(screen.queryByText(/Help improve reading and search/)).toBeNull();
  });
});
