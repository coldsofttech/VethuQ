import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App.jsx';
import { CATALOG, mockApi, renderWithProviders } from '../test/helpers.jsx';

// pdf.js cannot draw in jsdom: a stand-in whose pages hold one line of text.
const PAGE_TEXT = vi.hoisted(() => ({ items: ['the harvest of ', 'wheat', ' rose in autumn'] }));
const OPENED = vi.hoisted(() => ({ options: [] }));
vi.mock('../search/pdf/pdfjs.js', () => {
  class TextLayer {
    constructor({ container }) {
      this.container = container;
      this.textContentItemsStr = [];
      this.textDivs = [];
    }
    async render() {
      for (const text of PAGE_TEXT.items) {
        const span = document.createElement('span');
        span.textContent = text;
        this.container.appendChild(span);
        this.textDivs.push(span);
        this.textContentItemsStr.push(text);
      }
    }
    cancel() {}
  }
  const page = {
    getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }),
    streamTextContent: () => ({}),
  };
  const pdf = { numPages: 6, getPage: async () => page };
  return {
    documentOptions: (path) => ({ url: `/api/files/pdf?path=${encodeURIComponent(path)}` }),
    loadPdfjs: async () => ({
      TextLayer,
      getDocument: (options) => {
        OPENED.options.push(options);
        return { promise: Promise.resolve(pdf), destroy() {} };
      },
    }),
  };
});

const OPTIONS = {
  engines: [
    { id: 'exact', label: 'Exact', available: true, reason: '', options: {}, approximate: false },
    {
      id: 'fuzzy',
      label: 'Similar',
      available: true,
      reason: '',
      options: { threshold: 'balanced' },
      approximate: true,
    },
    {
      id: 'semantic',
      label: 'Meaning',
      available: false,
      reason: 'not installed',
      options: {},
      approximate: true,
    },
  ],
  normalizers: [
    { id: 'case', levels: ['match', 'ignore'], identity: 'match', version: '1', setting: 'auto' },
  ],
  file_types: [
    { id: 'pdf', label: 'PDF', extensions: ['.pdf'], available: true },
    { id: 'txt', label: 'Text', extensions: ['.txt'], available: true },
  ],
  defaults: { engine: 'all', context_chars: 80 },
};

const match = (over = {}) => ({
  file_id: 1,
  document_id: 1,
  file_name: 'report.pdf',
  file_path: '/docs/report.pdf',
  file_type: 'pdf',
  page_number: 3,
  total_pages: 12,
  before: 'the harvest of ',
  matched: 'wheat',
  after: ' rose in autumn',
  truncated_before: true,
  truncated_after: false,
  duplicate_of_path: null,
  source: 'native',
  score: null,
  start: 10,
  end: 15,
  engine: 'exact',
  matched_by: ['exact'],
  modifiers: [],
  ...over,
});

const RESULT = {
  query: 'wheat',
  engine: 'all',
  total: 3,
  levels: {},
  index_rebuilt: false,
  pending: {},
  options: {},
  matches: [
    match(),
    match({
      page_number: 5,
      start: 40,
      engine: 'fuzzy',
      matched_by: ['fuzzy', 'exact'],
      score: 0.83,
      modifiers: ['accents'],
    }),
    match({
      file_name: 'notes.txt',
      file_path: '/docs/notes.txt',
      file_type: 'txt',
      total_pages: 1,
      page_number: 1,
      source: 'native',
    }),
  ],
};

const ROUTES = {
  'GET /api/search/options': OPTIONS,
  'GET /api/sources': { sources: [{ id: 7, name: 'docs', path: '/docs' }] },
  'GET /api/catalog': CATALOG,
  'POST /api/search/run': RESULT,
};

const bodies = (fetchMock) =>
  fetchMock.mock.calls
    .filter(([p]) => p === '/api/search/run')
    .map(([, init]) => JSON.parse(init.body));

beforeEach(() => {
  localStorage.clear();
  OPENED.options.length = 0;
  PAGE_TEXT.items = ['the harvest of ', 'wheat', ' rose in autumn'];
});

const type = async (text) =>
  userEvent.type(await screen.findByRole('searchbox', { name: 'Search text' }), text);

describe('Search', () => {
  it('is a menu item with the box, the filters, and a keyboard button that is off', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    expect(await screen.findByRole('searchbox', { name: 'Search text' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'File types' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Engine' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled(); // nothing typed
    expect(
      screen.getByRole('button', { name: 'On-screen keyboard (coming later)' }),
    ).toBeDisabled();
    expect(screen.getAllByRole('tab', { name: 'Search' })[0]).toBeInTheDocument();
  });

  it('searches on Enter and shows the file, page, text with the match marked, and how it was found', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    expect(await within(table).findByText('report.pdf')).toBeInTheDocument();
    expect(within(table).getByText('notes.txt')).toBeInTheDocument();
    expect(within(table).getByText('3 of 12')).toBeInTheDocument();
    expect(table.querySelector('mark')).toHaveTextContent('wheat');
    expect(within(table).getByText('Similar 83%')).toBeInTheDocument();
    expect(within(table).getByText('+1')).toBeInTheDocument();
    expect(within(table).getByText('2 matches')).toBeInTheDocument();
    expect(screen.getByText(/3 matches in 2 files/)).toBeInTheDocument();
    expect(bodies(fetchMock)[0]).toEqual({ query: 'wheat', limit: 50, offset: 0 });
  });

  it('sends the file types, engine, case and sources that were chosen', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'File types' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'PDF' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Text' }));
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('combobox', { name: 'Engine' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Similar' }));
    await userEvent.click(screen.getByRole('button', { name: 'Match case' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Sources' }));
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'docs' }));
    await userEvent.keyboard('{Escape}');
    await type('wheat');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(1));
    expect(bodies(fetchMock)[0]).toMatchObject({
      query: 'wheat',
      engine: 'fuzzy',
      case_sensitive: true,
      file_types: ['pdf', 'txt'],
      sources: [7],
    });
  });

  it('puts an engine setting and a normalizer level from the options flyout in the request', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await userEvent.click(await screen.findByRole('combobox', { name: 'Engine' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Similar' }));
    await userEvent.click(screen.getByRole('button', { name: 'Search options' }));
    await userEvent.type(await screen.findByLabelText('threshold'), 'loose');
    await userEvent.click(screen.getByRole('combobox', { name: 'Normalizer case' }));
    await userEvent.click(await screen.findByRole('option', { name: 'ignore' }));
    await userEvent.keyboard('{Escape}');
    await type('wheat{Enter}');
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(1));
    expect(bodies(fetchMock)[0]).toMatchObject({
      engine: 'fuzzy',
      options: { fuzzy: { threshold: 'loose' } },
      normalize: { case: 'ignore' },
    });
  });

  it('says so when nothing matched, and when pages are not ready for an engine', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/search/run': {
        ...RESULT,
        total: 0,
        matches: [],
        pending: { semantic: 12 },
        index_rebuilt: true,
      },
    });
    renderWithProviders(<App />, { route: '/search' });
    await type('zzz{Enter}');
    expect(await screen.findByText(/^No matches\./)).toBeInTheDocument();
    expect(screen.getByText(/Meaning \(12 pages\)/)).toBeInTheDocument();
    expect(screen.getByText(/index was rebuilt/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export every match' })).toBeDisabled();
  });

  it('shows why a search failed', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/search/run': new Response(
        JSON.stringify({ error: 'The Similar engine cannot search this.' }),
        { status: 422 },
      ),
    });
    renderWithProviders(<App />, { route: '/search' });
    await type('a{Enter}');
    expect(await screen.findByText('The Similar engine cannot search this.')).toBeInTheDocument();
  });

  it('keeps recent searches, and runs one when it is picked', async () => {
    const fetchMock = mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    await screen.findByRole('table', { name: 'Search results' });
    await userEvent.click(screen.getByRole('button', { name: 'Recent searches' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'wheat' }));
    await waitFor(() => expect(bodies(fetchMock)).toHaveLength(2));
    expect(JSON.parse(localStorage.getItem('vethuq.recent-searches'))).toEqual(['wheat']);
  });

  it('opens the menu of a result, with Open off in a browser and Preview on for PDF, text and Markdown', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    await userEvent.pointer({
      keys: '[MouseRight]',
      target: await within(table).findByText('notes.txt'),
    });
    expect(await screen.findByRole('menuitem', { name: 'Open' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByRole('menuitem', { name: 'Preview' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByRole('menuitem', { name: 'Copy path' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Open in Sources' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('has no preview for a file type it cannot show', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/search/run': {
        ...RESULT,
        matches: [
          match({ file_name: 'plan.docx', file_path: '/docs/plan.docx', file_type: 'docx' }),
        ],
      },
    });
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    await userEvent.pointer({
      keys: '[MouseRight]',
      target: await within(table).findByText('plan.docx'),
    });
    expect(await screen.findByRole('menuitem', { name: 'Preview' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('shows the details of a match', async () => {
    mockApi(ROUTES);
    renderWithProviders(<App />, { route: '/search' });
    await type('wheat{Enter}');
    const table = await screen.findByRole('table', { name: 'Search results' });
    await userEvent.pointer({
      keys: '[MouseRight]',
      target: (await within(table).findAllByText('5 of 12'))[0],
    });
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Details' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('/docs/report.pdf')).toBeInTheDocument();
    expect(within(dialog).getByText('accents')).toBeInTheDocument();
    expect(within(dialog).getByText('83%')).toBeInTheDocument();
  });

  describe('open at the place of the match', () => {
    const DESKTOP = {
      'GET /api/platform': { kind: 'desktop', window_controls: true, open_file: true },
    };

    const openFrom = async (text) => {
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: await within(table).findByText(text),
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Open' }));
    };

    const opens = (fetchMock) =>
      fetchMock.mock.calls
        .filter(([p]) => p === '/api/os/open')
        .map(([, init]) => JSON.parse(init.body));

    it('asks for the page of a PDF match and says nothing when the app jumped', async () => {
      const fetchMock = mockApi({
        ...ROUTES,
        ...DESKTOP,
        'POST /api/os/open': { opened: true, jumped: true, hint: null },
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      await openFrom('3 of 12');
      await waitFor(() =>
        expect(opens(fetchMock)).toEqual([{ path: '/docs/report.pdf', page: 3 }]),
      );
      expect(screen.queryByText('Opened at the top')).not.toBeInTheDocument();
    });

    it('asks for the line of a text match, and says where to look when it opened at the top', async () => {
      const lined = {
        ...RESULT,
        matches: [
          match({
            file_name: 'notes.txt',
            file_path: '/docs/notes.txt',
            file_type: 'txt',
            total_pages: 1,
            page_number: 1,
            line: 12,
            column: 4,
          }),
        ],
      };
      const fetchMock = mockApi({
        ...ROUTES,
        ...DESKTOP,
        'POST /api/search/run': lined,
        'POST /api/os/open': { opened: true, jumped: false, hint: 'Go to line 12, column 4.' },
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      await openFrom('notes.txt');
      await waitFor(() =>
        expect(opens(fetchMock)).toEqual([{ path: '/docs/notes.txt', line: 12, column: 4 }]),
      );
      expect(await screen.findByText('Go to line 12, column 4.')).toBeInTheDocument();
    });
  });

  describe('the PDF preview', () => {
    beforeEach(() => {
      // jsdom has no layout: the panel is 624 pixels wide.
      vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(624);
      // The marked words are 400 pixels below the top of a 400 pixel tall panel.
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function () {
        return { top: this.textContent === 'wheat' ? 500 : 100 };
      });
    });

    const previewFrom = async (text) => {
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText(text))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'PDF preview' });
    };

    it('opens the file beside the results at the page of the match and marks the words', async () => {
      mockApi(ROUTES);
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await previewFrom('5 of 12');
      expect(within(panel).getByText('report.pdf')).toBeInTheDocument();
      expect(within(panel).getByText(/Match 2 of 2 · page 5/)).toBeInTheDocument();
      await waitFor(() => expect(OPENED.options).toHaveLength(1));
      expect(OPENED.options[0].url).toBe('/api/files/pdf?path=%2Fdocs%2Freport.pdf');
      // The results stay beside it.
      expect(screen.getByRole('table', { name: 'Search results' })).toBeInTheDocument();
      // The panel scrolled down to put the words in its middle (they are 200 below it).
      await waitFor(() => expect(panel.lastElementChild.scrollTop).toBeGreaterThan(150));
    });

    it('steps through the matches of the file', async () => {
      mockApi(ROUTES);
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await previewFrom('3 of 12');
      expect(within(panel).getByText(/Match 1 of 2 · page 3/)).toBeInTheDocument();
      expect(within(panel).getByRole('button', { name: 'Previous match' })).toBeDisabled();
      await userEvent.click(within(panel).getByRole('button', { name: 'Next match' }));
      expect(await within(panel).findByText(/Match 2 of 2 · page 5/)).toBeInTheDocument();
      expect(within(panel).getByRole('button', { name: 'Next match' })).toBeDisabled();
      await userEvent.click(within(panel).getByRole('button', { name: 'Previous match' }));
      expect(await within(panel).findByText(/Match 1 of 2 · page 3/)).toBeInTheDocument();
    });

    it('shows only the page when the words are not in its text, and closes', async () => {
      PAGE_TEXT.items = ['scanned image text'];
      mockApi(ROUTES);
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await previewFrom('3 of 12');
      expect(await within(panel).findByText(/are not in this page/)).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('button', { name: 'Close preview' }));
      expect(screen.queryByRole('region', { name: 'PDF preview' })).not.toBeInTheDocument();
    });
  });

  describe('the text preview', () => {
    const WINDOW = {
      total: 3,
      start: 0,
      lines: ['first line', 'second line has wheat in it', 'third'],
      file_name: 'notes.txt',
      file_path: '/docs/notes.txt',
      file_type: 'txt',
    };
    const LINED = {
      ...RESULT,
      matches: [
        match({
          file_name: 'notes.txt',
          file_path: '/docs/notes.txt',
          file_type: 'txt',
          document_id: 4,
          total_pages: 1,
          page_number: 1,
          line: 2,
          column: 17,
        }),
        match({
          file_name: 'notes.txt',
          file_path: '/docs/notes.txt',
          file_type: 'txt',
          document_id: 4,
          total_pages: 1,
          page_number: 1,
          start: 90,
          line: 3,
          column: 1,
        }),
      ],
    };

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    });

    const open = async () => {
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Text preview' });
    };

    it('shows the text beside the results at the line of the match, with the words marked', async () => {
      const fetchMock = mockApi({
        ...ROUTES,
        'POST /api/search/run': LINED,
        'GET /api/files/text': WINDOW,
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await open();
      expect(within(panel).getByText(/Match 1 of 2 · line 2/)).toBeInTheDocument();
      expect(await within(panel).findByText('first line')).toBeInTheDocument();
      expect(panel.textContent).toContain('second line has wheat in it');
      expect(panel.querySelector('mark').textContent).toBe('wheat');
      const asked = fetchMock.mock.calls
        .map(([url]) => url)
        .filter((u) => u.startsWith('/api/files/text'));
      expect(asked.some((u) => u.includes('document_id=4') && u.includes('count=200'))).toBe(true);
    });

    it('steps to the next match and closes', async () => {
      mockApi({ ...ROUTES, 'POST /api/search/run': LINED, 'GET /api/files/text': WINDOW });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await open();
      await userEvent.click(within(panel).getByRole('button', { name: 'Next match' }));
      expect(await within(panel).findByText(/Match 2 of 2 · line 3/)).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('button', { name: 'Close preview' }));
      expect(screen.queryByRole('region', { name: 'Text preview' })).not.toBeInTheDocument();
    });

    it('says why the text could not be shown', async () => {
      mockApi({
        ...ROUTES,
        'POST /api/search/run': LINED,
        'GET /api/files/text': Response.json(
          { error: 'That page is not in the index.' },
          { status: 404 },
        ),
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const panel = await open();
      expect(await within(panel).findByText(/not in the index/)).toBeInTheDocument();
    });
  });

  describe('the table preview', () => {
    const TABLE = {
      total: 3,
      all: 3,
      start: 0,
      rows: [
        ['Ada', '10'],
        ['Grace', '20'],
        ['Alan', '30'],
      ],
      numbers: [2, 3, 4],
      header: ['name', 'qty'],
      header_detected: true,
      columns: 2,
      widths: [8, 4],
      delimiter: ',',
      encoding: 'utf-8',
      file_name: 'people.csv',
      target: { row_number: 3, index: 1, column: 0 },
    };
    const CSV = {
      ...RESULT,
      matches: [
        match({
          file_name: 'people.csv',
          file_path: '/docs/people.csv',
          file_type: 'csv',
          document_id: 5,
          total_pages: 1,
          page_number: 1,
          matched: 'Grace',
          line: 3,
          column: 5,
        }),
      ],
    };

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(280);
    });

    const open = async () => {
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Table preview' });
    };

    const requests = (fetchMock) =>
      fetchMock.mock.calls
        .map(([url]) => url)
        .filter((u) => u.startsWith('/api/files/csv'))
        .map((u) => new URL(u, 'http://x').searchParams);

    const show = async (extra = {}) => {
      const fetchMock = mockApi({
        ...ROUTES,
        'POST /api/search/run': CSV,
        'GET /api/files/csv': TABLE,
        ...extra,
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('grace{Enter}');
      return { fetchMock, panel: await open() };
    };

    it('opens on the matching row with the cell and the words marked', async () => {
      const { fetchMock, panel } = await show();
      expect(within(panel).getByText(/Match 1 of 1 · row 3/)).toBeInTheDocument();
      expect(await within(panel).findByRole('columnheader', { name: /name/ })).toBeInTheDocument();
      expect(await within(panel).findByText('Ada')).toBeInTheDocument();
      expect(panel.querySelector('mark').textContent).toBe('Grace');
      expect(within(panel).getByText('3 rows')).toBeInTheDocument();
      const first = requests(fetchMock)[0];
      expect(first.get('path')).toBe('/docs/people.csv');
      expect([first.get('at_row'), first.get('at_offset')]).toEqual(['3', '5']);
      expect(within(panel).getByRole('switch', { name: 'First row is header' })).toBeChecked();
    });

    it('sorts by a column from its header: ascending, then descending, then off', async () => {
      const { fetchMock, panel } = await show();
      const head = await within(panel).findByRole('button', { name: /name/ });
      await userEvent.click(head);
      await waitFor(() => expect(requests(fetchMock).at(-1).get('sort')).toBe('0'));
      expect(requests(fetchMock).at(-1).get('dir')).toBeNull();
      await userEvent.click(within(panel).getByRole('button', { name: /name/ }));
      await waitFor(() => expect(requests(fetchMock).at(-1).get('dir')).toBe('desc'));
      await userEvent.click(within(panel).getByRole('button', { name: /name/ }));
      await waitFor(() => expect(requests(fetchMock).at(-1).get('sort')).toBeNull());
    });

    it('filters the rows in every column or one, and shows how many are left', async () => {
      const { fetchMock, panel } = await show({
        'GET /api/files/csv': {
          ...TABLE,
          total: 1,
          target: { row_number: 3, index: 0, column: 0 },
        },
      });
      await userEvent.type(
        await within(panel).findByRole('textbox', { name: 'Filter rows' }),
        'gr',
      );
      await waitFor(() => expect(requests(fetchMock).at(-1).get('filter')).toBe('gr'));
      expect(await within(panel).findByText('1 of 3 rows')).toBeInTheDocument();
      await userEvent.selectOptions(
        within(panel).getByRole('combobox', { name: 'Filter column' }),
        'qty',
      );
      await waitFor(() => expect(requests(fetchMock).at(-1).get('column')).toBe('1'));
      await userEvent.click(within(panel).getByRole('button', { name: 'Clear the filter' }));
      await waitFor(() => expect(requests(fetchMock).at(-1).get('filter')).toBeNull());
    });

    it('treats the first row as data when the header switch is turned off', async () => {
      const { fetchMock, panel } = await show();
      await userEvent.click(
        await within(panel).findByRole('switch', { name: 'First row is header' }),
      );
      await waitFor(() => expect(requests(fetchMock).at(-1).get('header')).toBe('0'));
    });

    it('says why the table could not be shown, and closes', async () => {
      const { panel } = await show({
        'GET /api/files/csv': Response.json(
          { error: 'This file is 90 MB, too large to preview.' },
          { status: 422 },
        ),
      });
      expect(await within(panel).findByText(/too large to preview/)).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('button', { name: 'Close preview' }));
      expect(screen.queryByRole('region', { name: 'Table preview' })).not.toBeInTheDocument();
    });
  });

  describe('the Markdown preview', () => {
    const SOURCE =
      '# Harvest\n\nThe price of **wheat** rose in autumn.\n\nSee [more](http://example.com/oats).\n';
    const FILE = { text: SOURCE, encoding: 'utf-8', file_name: 'report.md' };
    const found = (over = {}) => ({
      ...RESULT,
      matches: [
        match({
          file_name: 'report.md',
          file_path: '/docs/report.md',
          file_type: 'markdown',
          document_id: 6,
          total_pages: 1,
          page_number: 1,
          before: 'Harvest The price of ',
          matched: 'wheat',
          after: ' rose in autumn.',
          ...over,
        }),
      ],
    });

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    });

    const open = async () => {
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Markdown preview' });
    };

    const show = async (result, file = FILE) => {
      const fetchMock = mockApi({
        ...ROUTES,
        'POST /api/search/run': result,
        'GET /api/files/markdown': file,
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      return { fetchMock, panel: await open() };
    };

    it('shows the file rendered, at the match, with the words marked', async () => {
      const { fetchMock, panel } = await show(found());
      expect(await within(panel).findByRole('heading', { name: 'Harvest' })).toBeInTheDocument();
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('wheat'));
      expect(within(panel).getByText(/Match 1 of 1 · line 3/)).toBeInTheDocument();
      expect(within(panel).getByRole('tab', { name: 'Rendered' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      const asked = fetchMock.mock.calls
        .map(([url]) => url)
        .find((u) => u.includes('/files/markdown'));
      expect(asked).toBe('/api/files/markdown?path=%2Fdocs%2Freport.md');
      // A link is text, not something to click.
      expect(panel.querySelector('a')).toBeNull();
    });

    it('switches to the source, on the line of the match, and remembers the choice', async () => {
      const { panel } = await show(found());
      await within(panel).findByRole('heading', { name: 'Harvest' });
      await userEvent.click(within(panel).getByRole('tab', { name: 'Source' }));
      expect(await within(panel).findByText('# Harvest')).toBeInTheDocument();
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toMatch(/wheat/));
      expect(localStorage.getItem('vethuq.markdown-view')).toBe('source');
    });

    it('says when the match is in markup that does not show, and offers the source', async () => {
      const { panel } = await show(
        found({ before: 'See more http://example.com/', matched: 'oats', after: '' }),
      );
      expect(
        await within(panel).findByText(/not visible in the rendered view/),
      ).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('button', { name: 'Show source' }));
      expect(await within(panel).findByText('# Harvest')).toBeInTheDocument();
    });

    it('says when the words are not in the file as it is now', async () => {
      const { panel } = await show(found({ matched: 'zebra' }));
      expect(await within(panel).findByText(/not in the file as it is now/)).toBeInTheDocument();
    });

    it('does not offer Open at a line for a Markdown file', async () => {
      const fetchMock = mockApi({
        ...ROUTES,
        'GET /api/platform': { kind: 'desktop', window_controls: true, open_file: true },
        'POST /api/search/run': found({ line: 7, column: 3 }),
        'POST /api/os/open': { opened: true, jumped: true, hint: null },
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Open' }));
      await waitFor(() =>
        expect(
          fetchMock.mock.calls
            .filter(([p]) => p === '/api/os/open')
            .map(([, init]) => JSON.parse(init.body)),
        ).toEqual([{ path: '/docs/report.md' }]),
      );
    });
  });

  describe('the CSS preview', () => {
    const SHEET = 'a {\n  color: red;\n}\n.card {\n  margin: 0;\n}\n';
    const FILE = { text: SHEET, encoding: 'utf-8', file_name: 'site.css', longest_line: 14 };
    const found = (over = {}) => ({
      ...RESULT,
      matches: [
        match({
          file_name: 'site.css',
          file_path: '/docs/site.css',
          file_type: 'css',
          document_id: 7,
          total_pages: 1,
          page_number: 1,
          before: 'a { color: red; } .card { ',
          matched: 'margin',
          after: ': 0; }',
          ...over,
        }),
      ],
    });

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    });

    const show = async (file = FILE, result = found()) => {
      mockApi({ ...ROUTES, 'POST /api/search/run': result, 'GET /api/files/css': file });
      renderWithProviders(<App />, { route: '/search' });
      await type('margin{Enter}');
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Code preview' });
    };

    it('shows the sheet with line numbers and colours, at the line of the match, marked', async () => {
      const panel = await show();
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('margin'));
      expect(within(panel).getByText(/Match 1 of 1 · line 5/)).toBeInTheDocument();
      const row = panel.querySelector('[data-line="5"]');
      expect(row.querySelector('mark').style.color).not.toBe('');
      // The selector and the property are different colours (the light theme here).
      const colours = (line) =>
        [...panel.querySelector(`[data-line="${line}"]`).querySelectorAll('span span')].map((n) => [
          n.textContent.trim(),
          n.style.color,
        ]);
      const selector = colours(4).find(([text]) => text === '.card');
      const property = colours(2).find(([text]) => text === 'color');
      expect(selector[1]).not.toBe('');
      expect(selector[1]).not.toBe(property[1]);
      expect(within(panel).getByRole('tab', { name: 'Source' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
    });

    it('opens a minified sheet formatted, and the switch shows the source', async () => {
      const minified = {
        text: 'a{color:red}.card{margin:0}',
        encoding: 'utf-8',
        file_name: 'site.min.css',
        longest_line: 5000,
      };
      const panel = await show(minified);
      expect(within(panel).getByRole('tab', { name: 'Formatted' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('margin'));
      // Formatted: "a {", "  color:red;", "}", ".card {", "  margin:0", "}": line 5.
      expect(within(panel).getByText(/line 5/)).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('tab', { name: 'Source' }));
      await waitFor(() => expect(within(panel).getByText(/line 1\b/)).toBeInTheDocument());
      expect(panel.querySelector('mark')?.textContent).toBe('margin');
    });

    it('says when the words are not in the file as it is now', async () => {
      const panel = await show(FILE, found({ matched: 'zebra' }));
      expect(await within(panel).findByText(/not in the file as it is now/)).toBeInTheDocument();
    });
  });

  describe('the web page preview', () => {
    const PAGE =
      '<html><head><title>wheat news</title></head><body>\n<h1>Harvest</h1>\n<p>The price of <b>wheat</b> rose.</p>\n</body></html>';
    const FILE = { text: PAGE, encoding: 'utf-8', file_name: 'page.html', longest_line: 100 };
    const found = (over = {}) => ({
      ...RESULT,
      matches: [
        match({
          file_name: 'page.html',
          file_path: '/docs/page.html',
          file_type: 'html',
          document_id: 8,
          total_pages: 1,
          page_number: 1,
          before: 'Harvest The price of ',
          matched: 'wheat',
          after: ' rose.',
          ...over,
        }),
      ],
    });

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    });

    const show = async (file = FILE, result = found()) => {
      mockApi({ ...ROUTES, 'POST /api/search/run': result, 'GET /api/files/html': file });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Web page preview' });
    };

    // jsdom does not load a frame's `srcdoc` itself: put the page in, as a browser would.
    const loadFrame = (panel) => {
      const frame = panel.querySelector('iframe');
      const doc = frame.contentDocument;
      doc.open();
      doc.write(frame.getAttribute('srcdoc'));
      doc.close();
      fireEvent.load(frame);
      return frame;
    };

    it('shows the page rendered in a frame that runs nothing, with the words marked', async () => {
      const panel = await show();
      const frame = await waitFor(() => {
        const found = panel.querySelector('iframe');
        expect(found).not.toBeNull();
        return found;
      });
      expect(frame.getAttribute('sandbox')).toBe('allow-same-origin');
      expect(frame.getAttribute('srcdoc')).toContain('<h1>Harvest</h1>');
      loadFrame(panel);
      await waitFor(() =>
        expect(frame.contentDocument.querySelector('mark')?.textContent).toBe('wheat'),
      );
      expect(within(panel).getByRole('tab', { name: 'Rendered' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
    });

    it('shows the source, coloured, on the line of the match, and remembers the choice', async () => {
      const panel = await show();
      await userEvent.click(await within(panel).findByRole('tab', { name: 'Source' }));
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('wheat'));
      expect(within(panel).getByText(/Match 1 of 1 · line 3/)).toBeInTheDocument();
      const tag = [...panel.querySelectorAll('[data-line="2"] span span')].find(
        (n) => n.textContent === 'h1',
      );
      expect(tag.style.color).not.toBe('');
      expect(localStorage.getItem('vethuq.html-view')).toBe('source');
    });

    it('lays the page out one tag to a line in the formatted view', async () => {
      const panel = await show();
      await userEvent.click(await within(panel).findByRole('tab', { name: 'Formatted' }));
      expect(await within(panel).findByText(/Match 1 of 1 · line \d+/)).toBeInTheDocument();
      await waitFor(() => expect(panel.querySelector('[data-line="3"]')).not.toBeNull());
      expect(panel.querySelector('[data-line="1"]').textContent).toContain('<html>');
      expect(panel.querySelector('mark')?.textContent).toBe('wheat');
    });

    it('says when the match is in text the page does not show, and offers the source', async () => {
      const panel = await show(FILE, found({ before: '', matched: 'news', after: '' }));
      await waitFor(() => expect(panel.querySelector('iframe')).not.toBeNull());
      loadFrame(panel);
      expect(
        await within(panel).findByText(/not visible on the rendered page/),
      ).toBeInTheDocument();
      await userEvent.click(within(panel).getByRole('button', { name: 'Show source' }));
      // The source opens on the title, where the words are.
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('news'));
      expect(within(panel).getByText(/line 1\b/)).toBeInTheDocument();
    });

    it('shows the source of a page too large to render', async () => {
      const big = { ...FILE, text: `<p>${'x'.repeat(5 * 1024 * 1024)} wheat</p>` };
      const panel = await show(big);
      expect(await within(panel).findByText(/too large to render/)).toBeInTheDocument();
      expect(within(panel).getByRole('tab', { name: 'Rendered' })).toBeDisabled();
      expect(panel.querySelector('iframe')).toBeNull();
    });

    it('says when the words are not in the page as it is now', async () => {
      localStorage.setItem('vethuq.html-view', 'source');
      const panel = await show(FILE, found({ matched: 'zebra' }));
      expect(await within(panel).findByText(/not in the page as it is now/)).toBeInTheDocument();
    });
  });

  describe('the JSON, YAML, JavaScript and XML previews', () => {
    const CASES = {
      json: {
        text: '{\n  "a": { "port": 80 },\n  "b": { "ports": [8080] },\n  "c": { "port": 8080 }\n}',
        // Indexed as `c.port: 8080`: the value under "port", the second 8080 under it.
        match: { before: 'a.port: 80 b.ports[0]: 8080 c.port: ', matched: '8080', after: '' },
        line: 4,
        mark: '8080',
        label: 'JSON',
      },
      yaml: {
        text: 'server:\n  host: a\n  ports:\n    - 8080\n  debug: yes\n',
        match: { before: 'server.host: a server.debug: ', matched: 'yes', after: '' },
        line: 5,
        mark: 'yes',
        label: 'YAML',
      },
      js: {
        text: 'const price = 3;\n/* wheat */\nexport function wheat() { return price; }\n',
        match: { before: '/* wheat */ export function ', matched: 'wheat', after: '() { return' },
        line: 3,
        mark: 'wheat',
        label: 'JavaScript',
      },
      xml: {
        text: '<?xml version="1.0"?>\n<catalog>\n  <book id="7">Dune</book>\n</catalog>\n',
        match: { before: 'catalog/book@id: 7 catalog/book: ', matched: 'Dune', after: '' },
        line: 3,
        mark: 'Dune',
        label: 'XML',
      },
    };

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    });

    const show = async (kind, file, words) => {
      const result = {
        ...RESULT,
        matches: [
          match({
            file_name: `sample.${kind}`,
            file_path: `/docs/sample.${kind}`,
            file_type: kind,
            document_id: 9,
            total_pages: 1,
            page_number: 1,
            ...words,
          }),
        ],
      };
      mockApi({
        ...ROUTES,
        'POST /api/search/run': result,
        [`GET /api/files/${kind}`]: file,
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText('1 of 1'))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      return screen.findByRole('region', { name: 'Code preview' });
    };

    for (const [type, c] of Object.entries(CASES)) {
      it(`shows a ${c.label} file coloured, on the line of the match, marked`, async () => {
        const panel = await show(
          type,
          { text: c.text, encoding: 'utf-8', file_name: `sample.${type}`, longest_line: 60 },
          c.match,
        );
        await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe(c.mark));
        expect(
          within(panel).getByText(new RegExp(`Match 1 of 1 · line ${c.line}\\b`)),
        ).toBeInTheDocument();
        expect(panel.querySelector('mark').closest('[data-line]').dataset.line).toBe(
          String(c.line),
        );
        // The text is in more than one colour.
        const colours = new Set(
          [...panel.querySelectorAll('[data-line] span span')]
            .map((n) => n.style.color)
            .filter(Boolean),
        );
        expect(colours.size).toBeGreaterThan(1);
      });
    }

    it('opens a minified JSON file formatted, and the switch shows the source', async () => {
      const minified = '{"a":{"port":80},"b":{"ports":[8080]},"c":{"port":8080}}';
      const panel = await show(
        'json',
        { text: minified, encoding: 'utf-8', file_name: 'sample.json', longest_line: 5000 },
        CASES.json.match,
      );
      expect(within(panel).getByRole('tab', { name: 'Formatted' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      // Formatted, one value to a line: the third "port" is on line 11.
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('8080'));
      expect(panel.querySelector('mark').closest('[data-line]').textContent).toContain(
        '"port": 8080',
      );
      await userEvent.click(within(panel).getByRole('tab', { name: 'Source' }));
      await waitFor(() => expect(within(panel).getByText(/line 1\b/)).toBeInTheDocument());
    });

    it('has no Formatted view for YAML, which is readable as it is', async () => {
      const { text, match: words } = CASES.yaml;
      const panel = await show(
        'yaml',
        { text, encoding: 'utf-8', file_name: 'sample.yaml', longest_line: 9000 },
        words,
      );
      await waitFor(() => expect(panel.querySelector('mark')).not.toBeNull());
      expect(within(panel).queryByRole('tab', { name: 'Formatted' })).toBeNull();
    });
  });

  describe('the picture preview', () => {
    const TEXT = {
      total: 3,
      start: 0,
      lines: ['first line here', 'second has wheat in it', 'third line'],
      file_name: 'scan.png',
      file_type: 'png',
    };
    const found = (over = {}) => ({
      ...RESULT,
      matches: [
        match({
          file_name: 'scan.png',
          file_path: '/docs/scan.png',
          file_type: 'png',
          document_id: 11,
          total_pages: 1,
          page_number: 1,
          before: 'first line here second has ',
          matched: 'wheat',
          after: ' in it third line',
          start: 27,
          end: 32,
          boxes: [[0.55, 0.2, 0.73, 0.28]],
          ...over,
        }),
      ],
    });

    beforeEach(() => {
      vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400);
      vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(300);
    });

    const show = async (result = found(), routes = {}) => {
      const fetchMock = mockApi({
        ...ROUTES,
        'POST /api/search/run': result,
        'GET /api/files/text': TEXT,
        ...routes,
      });
      renderWithProviders(<App />, { route: '/search' });
      await type('wheat{Enter}');
      const table = await screen.findByRole('table', { name: 'Search results' });
      await userEvent.pointer({
        keys: '[MouseRight]',
        target: (await within(table).findAllByText(/\d of \d/))[0],
      });
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Preview' }));
      const panel = await screen.findByRole('region', { name: 'Picture preview' });
      return { fetchMock, panel };
    };

    // jsdom loads no pictures: say it has loaded one that is 800 x 600.
    const loaded = (panel) => {
      const image = panel.querySelector('img');
      Object.defineProperty(image, 'naturalWidth', { value: 800, configurable: true });
      Object.defineProperty(image, 'naturalHeight', { value: 600, configurable: true });
      fireEvent.load(image);
      return image;
    };

    it('shows the picture with the match boxed and the text read from it with the match marked', async () => {
      const { panel } = await show();
      const image = loaded(panel);
      expect(image.getAttribute('src')).toBe('/api/files/png?path=%2Fdocs%2Fscan.png');
      expect(within(panel).getByText(/Match 1 of 1 · picture/)).toBeInTheDocument();
      const box = panel.querySelector('[data-box]');
      expect(box.style.left).toBe('55%');
      expect(box.style.top).toBe('20%');
      const text = within(panel).getByRole('region', { name: 'Text read from the picture' });
      await waitFor(() => expect(text.querySelector('mark')?.textContent).toBe('wheat'));
      expect(text.querySelector('mark').parentElement.textContent).toBe('second has wheat in it');
    });

    it('says where on the picture is not known when the engine did not say', async () => {
      const { panel } = await show(found({ boxes: null }));
      loaded(panel);
      expect(panel.querySelector('[data-box]')).toBeNull();
      expect(await within(panel).findByText(/not known/)).toBeInTheDocument();
      await waitFor(() => expect(panel.querySelector('mark')?.textContent).toBe('wheat'));
    });

    it('zooms and turns the picture', async () => {
      const { panel } = await show();
      const image = loaded(panel);
      expect(image.style.width).toBe('400px'); // fitted: 800 x 600 into 400 x 300
      await userEvent.click(within(panel).getByRole('button', { name: '100%' }));
      expect(image.style.width).toBe('800px');
      await userEvent.click(within(panel).getByRole('button', { name: 'Zoom out' }));
      expect(image.style.width).toBe('640px');
      await userEvent.click(within(panel).getByRole('button', { name: 'Fit to the panel' }));
      expect(image.style.width).toBe('400px');
      await userEvent.click(within(panel).getByRole('button', { name: 'Turn right' }));
      expect(image.style.transform).toBe('rotate(90deg)');
      await userEvent.click(within(panel).getByRole('button', { name: 'Turn left' }));
      await userEvent.click(within(panel).getByRole('button', { name: 'Turn left' }));
      expect(image.style.transform).toBe('rotate(270deg)');
    });

    it('opens a TIFF at the frame of the match and goes from frame to frame', async () => {
      const tiff = found({
        file_name: 'scan.tiff',
        file_path: '/docs/scan.tiff',
        file_type: 'tiff',
        total_pages: 3,
        page_number: 2,
      });
      const { fetchMock, panel } = await show(tiff);
      let image = loaded(panel);
      expect(image.getAttribute('src')).toBe('/api/files/tiff?path=%2Fdocs%2Fscan.tiff&page=2');
      expect(within(panel).getByText(/frame 2 of 3/)).toBeInTheDocument();
      expect(panel.querySelector('[data-box]')).not.toBeNull();
      await userEvent.click(within(panel).getByRole('button', { name: 'Next frame' }));
      await waitFor(() =>
        expect(panel.querySelector('img').getAttribute('src')).toContain('page=3'),
      );
      expect(within(panel).getByRole('button', { name: 'Next frame' })).toBeDisabled();
      image = loaded(panel);
      // The box belongs to frame 2, and the text of frame 3 is asked for.
      expect(panel.querySelector('[data-box]')).toBeNull();
      const asked = fetchMock.mock.calls
        .map(([url]) => url)
        .filter((u) => u.startsWith('/api/files/text'));
      expect(asked.some((u) => u.includes('page=3'))).toBe(true);
      await userEvent.click(within(panel).getByRole('button', { name: 'Previous frame' }));
      await userEvent.click(within(panel).getByRole('button', { name: 'Previous frame' }));
      await waitFor(() =>
        expect(panel.querySelector('img').getAttribute('src')).toContain('page=1'),
      );
      expect(image).toBeDefined();
    });

    it('says why a picture could not be shown', async () => {
      const { panel } = await show(found(), {
        'GET /api/files/png': Response.json(
          { error: 'This frame is 90 megapixels, too large to preview.' },
          { status: 422 },
        ),
      });
      fireEvent.error(panel.querySelector('img'));
      expect(await within(panel).findByText(/too large to preview/)).toBeInTheDocument();
    });

    it('says when no text was read, and does not open a picture at a line', async () => {
      const { panel } = await show(found(), {
        'GET /api/files/text': { total: 0, start: 0, lines: [], file_name: 'scan.png' },
      });
      expect(await within(panel).findByText(/No text was read/)).toBeInTheDocument();
    });
  });
});
