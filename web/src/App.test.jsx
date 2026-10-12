import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from './App.jsx';
import { ABOUT, mockApi, renderWithProviders } from './test/helpers.jsx';

const ROUTES = {
  'GET /api/platform': { kind: 'web', window_controls: false },
  'GET /api/about': ABOUT,
};

describe('App', () => {
  it('shows the engine version on the home page', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />);
    expect(await screen.findByText('VethuQ 1.2.3')).toBeInTheDocument();
    expect(screen.getByTestId('app-shell')).toBeInTheDocument();
  });

  it('navigates to the about page and lists the installation details', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />);
    await userEvent.click(await screen.findByRole('tab', { name: 'About' }));
    expect(await screen.findByText('3.12.0')).toBeInTheDocument();
    expect(screen.getByText('Windows-11')).toBeInTheDocument();
  });

  it('remembers the chosen theme', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/settings' });
    await userEvent.click(await screen.findByRole('radio', { name: 'Dark' }));
    expect(window.localStorage.getItem('vethuq.theme')).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('shows an error when the service cannot be reached', async () => {
    mockApi({ 'GET /api/platform': { kind: 'web', window_controls: false } });
    renderWithProviders(<App />);
    expect(await screen.findByText('Could not load this information.')).toBeInTheDocument();
  });
});
