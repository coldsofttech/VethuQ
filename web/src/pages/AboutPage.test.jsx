import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App.jsx';
import { ABOUT, CATALOG, mockApi, renderWithProviders } from '../test/helpers.jsx';

const REPORT = '## VethuQ support information\n\n- VethuQ: 1.2.3\n';

const ROUTES = {
  'GET /api/platform': { kind: 'desktop', window_controls: false, folder_dialog: false },
  'GET /api/about': ABOUT,
  'GET /api/catalog': CATALOG,
  'GET /api/support-info': new Response(REPORT, { status: 200 }),
};

afterEach(() => {
  vi.restoreAllMocks();
  document.execCommand = undefined;
});

function withClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

describe('About > Copy support information', () => {
  it('copies the report with the interface details and says it worked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    withClipboard(writeText);
    mockApi({
      ...ROUTES,
      // A fresh Response per call: a body can be read once.
      'GET /api/support-info': () => new Response(REPORT, { status: 200 }),
    });
    renderWithProviders(<App />, { route: '/about' });
    await userEvent.click(await screen.findByRole('button', { name: 'Copy support information' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0];
    expect(copied).toContain('## VethuQ support information');
    expect(copied).toContain('- VethuQ: 1.2.3');
    expect(copied).toContain('### Interface');
    expect(copied).toContain('- Host: Desktop application');
    expect(copied).toContain(navigator.userAgent);
    expect(
      await screen.findByRole('button', { name: 'Copied to the clipboard' }),
    ).toBeInTheDocument();
  });

  it('falls back to selecting the text when the clipboard API refuses', async () => {
    withClipboard(vi.fn().mockRejectedValue(new Error('denied')));
    document.execCommand = vi.fn().mockReturnValue(true);
    mockApi({
      ...ROUTES,
      'GET /api/support-info': () => new Response(REPORT, { status: 200 }),
    });
    renderWithProviders(<App />, { route: '/about' });
    await userEvent.click(await screen.findByRole('button', { name: 'Copy support information' }));
    expect(
      await screen.findByRole('button', { name: 'Copied to the clipboard' }),
    ).toBeInTheDocument();
    expect(document.execCommand).toHaveBeenCalledWith('copy');
  });

  it('says so when nothing could be copied', async () => {
    withClipboard(vi.fn().mockRejectedValue(new Error('denied')));
    document.execCommand = vi.fn().mockReturnValue(false);
    mockApi({
      ...ROUTES,
      'GET /api/support-info': () => new Response(REPORT, { status: 200 }),
    });
    renderWithProviders(<App />, { route: '/about' });
    await userEvent.click(await screen.findByRole('button', { name: 'Copy support information' }));
    expect(await screen.findByText(/Could not copy/)).toBeInTheDocument();
  });

  it('says what the copy contains, and what it leaves out', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/about' });
    expect(await screen.findByText(/without folders or file names/)).toBeInTheDocument();
  });
});
