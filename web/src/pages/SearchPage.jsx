import {
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload20Regular } from '@fluentui/react-icons';
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { LoadMore } from '../credits/LoadMore.jsx';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import {
  EMPTY_FORM,
  forgetSearches,
  recentSearches,
  rememberSearch,
  toRequest,
} from '../search/form.js';
import { MatchDetails } from '../search/MatchDetails.jsx';
import { ResultsList } from '../search/ResultsList.jsx';
import { SearchBar } from '../search/SearchBar.jsx';
import { useSearch } from '../search/useSearch.js';
import { placeOf } from '../search/form.js';

// pdf.js is large, so the previews load when a file is first previewed.
const PdfPreview = lazy(() => import('../search/pdf/PdfPreview.jsx'));
const TextPreview = lazy(() => import('../search/text/TextPreview.jsx'));
const MarkdownPreview = lazy(() => import('../search/markdown/MarkdownPreview.jsx'));
const ImagePreview = lazy(() => import('../search/image/ImagePreview.jsx'));
const CodePreview = lazy(() => import('../search/code/CodePreview.jsx'));
const HtmlPreview = lazy(() => import('../search/html/HtmlPreview.jsx'));
const TablePreview = lazy(() => import('../search/table/TablePreview.jsx'));

const PREVIEWS = {
  pdf: PdfPreview,
  csv: TablePreview,
  tsv: TablePreview,
  parquet: TablePreview,
  txt: TextPreview,
  markdown: MarkdownPreview,
  css: CodePreview,
  json: CodePreview,
  ndjson: CodePreview,
  yaml: CodePreview,
  js: CodePreview,
  xml: CodePreview,
  png: ImagePreview,
  jpg: ImagePreview,
  tiff: ImagePreview,
  bmp: ImagePreview,
  gif: ImagePreview,
  webp: ImagePreview,
  html: HtmlPreview,
  mhtml: HtmlPreview,
};

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  split: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
    gap: tokens.spacingHorizontalM,
    alignItems: 'start',
  },
  side: { position: 'sticky', top: 0, height: '78vh', minHeight: 0 },
  results: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, minWidth: 0 },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
  muted: { color: tokens.colorNeutralForeground3 },
});

export function SearchPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const notify = useNotify();
  const platform = usePlatform();
  const { start } = useIndexing();
  const [options, setOptions] = useState(null);
  const [sources, setSources] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [recent, setRecent] = useState(recentSearches);
  const [details, setDetails] = useState(null);
  const [preview, setPreview] = useState(null);
  const [reindexing, setReindexing] = useState(null);
  const search = useSearch();

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.search.options(controller.signal),
      api.sources.list({}, controller.signal),
      api.catalog(controller.signal),
    ]).then(
      ([found, listed, catalog]) => {
        setOptions(found);
        setSources(listed.sources);
        setLanguages(catalog.languages.filter((l) => l.available));
      },
      (failure) => failure?.name !== 'AbortError' && setLoadError(failure),
    );
    return () => controller.abort();
  }, []);

  const labels = useMemo(
    () => Object.fromEntries((options?.engines ?? []).map((e) => [e.id, e.label])),
    [options],
  );

  const go = useCallback(
    (query) => {
      const next = typeof query === 'string' ? { ...form, query } : form;
      if (typeof query === 'string') setForm(next);
      if (!next.query.trim()) return;
      setRecent(rememberSearch(next.query));
      search.run(toRequest(next));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [form, search.run],
  );

  const sourceFor = useCallback(
    (path) =>
      [...sources]
        .sort((a, b) => b.path.length - a.path.length)
        .find(
          (s) =>
            path === s.path || path.startsWith(s.path.replace(/[\\/]+$/, '') + path[s.path.length]),
        ),
    [sources],
  );

  const actions = useMemo(
    () => ({
      open: async (match) => {
        if (!platform.openFile) return;
        try {
          const result = await api.os.open(match.file_path, placeOf(match));
          if (result && result.opened && !result.jumped && result.hint) {
            notify({ title: 'Opened at the top', body: result.hint, intent: 'info' });
          }
        } catch (failure) {
          notify({ title: 'Could not open the file', body: failure.message, intent: 'error' });
        }
      },
      reveal: (match) => api.os.reveal(match.file_path).catch(() => {}),
      hasSource: (match) => Boolean(sourceFor(match.file_path)),
      openInSources: (match) => navigate(`/sources/${sourceFor(match.file_path).id}`),
      copy: async (text, done) => {
        try {
          await navigator.clipboard.writeText(text);
          notify({ title: done });
        } catch {
          notify({ title: 'Could not copy', intent: 'warning' });
        }
      },
      details: setDetails,
      preview: (match) => {
        const same = search.items.filter((m) => m.file_path === match.file_path);
        const at = same.findIndex(
          (m) => m.page_number === match.page_number && m.start === match.start,
        );
        setPreview({ path: match.file_path, index: Math.max(0, at) });
      },
      reindex: setReindexing,
    }),
    [platform.openFile, notify, navigate, sourceFor, search.items],
  );

  const exportAll = async (format) => {
    try {
      await api.search.exportFile({ ...search.request, format });
    } catch (failure) {
      notify({ title: 'Could not export', body: failure.message, intent: 'error' });
    }
  };

  const reindex = async () => {
    const { file_path: path } = reindexing;
    setReindexing(null);
    if (await start('file', path))
      notify({
        title: 'Reindexing started',
        body: 'It may cost credits again for scanned pages.',
        intent: 'info',
      });
  };

  const previewMatches = useMemo(
    () => (preview ? search.items.filter((m) => m.file_path === preview.path) : []),
    [preview, search.items],
  );
  const previewing = preview !== null && previewMatches.length > 0;
  const Preview = PREVIEWS[previewMatches[0]?.file_type] ?? TextPreview;
  const files = new Set(search.items.map((m) => m.file_path)).size;
  const pending = Object.entries(search.pending);

  return (
    <div className={styles.page}>
      <PageHeader title="Search" lead="Find words in everything VethuQ has read." />
      {loadError && (
        <MessageBar intent="error">
          <MessageBarBody>{loadError.message}</MessageBarBody>
        </MessageBar>
      )}
      {!options && !loadError && <Spinner size="small" label="Loading" />}
      {options && (
        <SearchBar
          form={form}
          setForm={setForm}
          options={options}
          sources={sources}
          languages={languages}
          recent={recent}
          busy={search.loading && search.items.length === 0}
          onSearch={go}
          onClearRecent={() => {
            forgetSearches();
            setRecent([]);
          }}
        />
      )}
      {search.error && (
        <MessageBar intent="error">
          <MessageBarBody>{search.error.message}</MessageBarBody>
        </MessageBar>
      )}
      {search.indexRebuilt && (
        <MessageBar intent="info">
          <MessageBarBody>
            The search index was rebuilt first, because search add-ons changed.
          </MessageBarBody>
        </MessageBar>
      )}
      {pending.length > 0 && (
        <MessageBar intent="warning">
          <MessageBarBody>
            Some pages cannot be searched by{' '}
            {pending.map(([id, count]) => `${labels[id] ?? id} (${count} pages)`).join(', ')} yet:
            they are not prepared.
          </MessageBarBody>
        </MessageBar>
      )}
      {search.done && !search.error && (
        <div className={styles.bar}>
          <Text className={styles.muted}>
            {search.total === 0
              ? 'No matches.'
              : `${search.total.toLocaleString()} ${search.total === 1 ? 'match' : 'matches'}${
                  search.items.length < search.total
                    ? `, ${search.items.length.toLocaleString()} shown in ${files} files`
                    : ` in ${files} files`
                }`}
            {search.engine ? ` · engine: ${labels[search.engine] ?? search.engine}` : ''}
          </Text>
          <span className={styles.grow} />
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <ToolButton
                label="Export every match"
                icon={<ArrowDownload20Regular />}
                disabled={search.total === 0}
              />
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem onClick={() => exportAll('html')}>As a web page (HTML)</MenuItem>
                <MenuItem onClick={() => exportAll('json')}>As JSON</MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        </div>
      )}
      {search.done && search.total === 0 && !search.error && (
        <Text className={styles.muted}>
          Nothing matched. Try other words, fewer filters, or an engine that finds similar words
          (Similar, Meaning).
        </Text>
      )}
      <div className={previewing ? styles.split : undefined}>
        <div className={styles.results}>
          {search.items.length > 0 && (
            <ResultsList
              matches={search.items}
              labels={labels}
              actions={actions}
              platform={platform}
              compact={previewing}
            />
          )}
          <LoadMore more={search.hasMore} loading={search.loading} onMore={search.more} />
        </div>
        {previewing && (
          <div className={styles.side}>
            <Suspense fallback={<Spinner size="small" label="Opening the preview" />}>
              <Preview
                matches={previewMatches}
                index={preview.index}
                onIndex={(index) => setPreview({ ...preview, index })}
                onClose={() => setPreview(null)}
              />
            </Suspense>
          </div>
        )}
      </div>
      <MatchDetails match={details} labels={labels} onClose={() => setDetails(null)} />
      <ConfirmDialog
        open={reindexing !== null}
        title="Reindex this file?"
        confirmLabel="Reindex"
        onConfirm={reindex}
        onCancel={() => setReindexing(null)}
      >
        {reindexing?.file_name} is read again. Pages that need OCR cost credits again.
      </ConfirmDialog>
    </div>
  );
}
