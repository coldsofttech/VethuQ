import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { mockApi, renderWithProviders } from '../test/helpers.jsx';
import { TitleBar } from './TitleBar.jsx';

describe('TitleBar', () => {
  it('shows no window controls on a host without them', async () => {
    mockApi({ 'GET /api/platform': { kind: 'web', window_controls: false } });
    renderWithProviders(<TitleBar />);
    expect(await screen.findByText('VethuQ')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  });

  it('shows window controls on the desktop host and asks it to maximise', async () => {
    const fetchMock = mockApi({
      'GET /api/platform': { kind: 'desktop', window_controls: true },
      'GET /api/window/state': { maximized: false },
      'POST /api/window/maximize': { maximized: true },
      'POST /api/window/restore': { maximized: false },
    });
    renderWithProviders(<TitleBar />);

    await userEvent.click(await screen.findByRole('button', { name: 'Maximize' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/window/maximize',
      expect.objectContaining({ method: 'POST' }),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Restore' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Maximize' })).toBeInTheDocument(),
    );
  });
});
