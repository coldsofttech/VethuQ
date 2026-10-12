import {
  Breadcrumb,
  BreadcrumbButton,
  BreadcrumbDivider,
  BreadcrumbItem,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Menu,
  MenuDivider,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowSync20Regular,
  Copy20Regular,
  FolderOpen20Regular,
  Info20Regular,
  Play20Regular,
  Search20Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client.js';
import { FileIcon, SourceIcon } from '../components/FileIcon.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { download, formatBytes, formatCredits, formatDate } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { LanguagesDialog } from '../sources/LanguagesDialog.jsx';
import { SourceMenuItems } from '../sources/SourceMenuItems.jsx';
import { useSourceActions } from '../sources/useSourceActions.js';

const PAGE = 200;

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  head: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  grow: { flexGrow: 1 },
  filters: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: tokens.spacingHorizontalM,
  },
  name: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, minWidth: 0 },
  muted: { color: tokens.colorNeutralForeground3 },
  detail: {
    display: 'grid',
    gridTemplateColumns: 'max-content 1fr',
    gap: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalL}`,
  },
});

const COLUMNS = [
  { key: 'name', label: 'File' },
  { key: 'type', label: 'File type' },
  { key: 'status', label: 'Status' },
  { key: 'credits', label: 'Credits' },
];

/** What a file's status reads as; a locked file says why. */
function statusOf(file) {
  return file.protected
    ? { status: 'unsupported', title: file.error || 'Password protected' }
    : { status: file.status ?? 'pending', title: file.error ?? undefined };
}

export function SourceDetailPage() {
  const styles = useStyles();
  const { id } = useParams();
  const navigate = useNavigate();
  const platform = usePlatform();
  const { state, version, start } = useIndexing();
  const actions = useSourceActions();

  const [source, setSource] = useState(
    /** @type {import('../api/client.js').SourceRow | null} */ (null),
  );
  const [files, setFiles] = useState(/** @type {import('../api/client.js').FileRow[]} */ ([]));
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState({ status: {}, type: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [type, setType] = useState('');
  const [sort, setSort] = useState({ key: 'path', order: 'asc' });
  const [details, setDetails] = useState(null);
  const [languages, setLanguages] = useState(false);
  const sentinel = useRef(null);
  const token = useRef(0);

  const filters = { q: query, status, type, sort: sort.key, order: sort.order };

  const load = useCallback(
    async (offset, signal) => {
      const mine = ++token.current;
      setLoading(true);
      try {
        const page = await api.sources.files(id, { ...filters, offset, limit: PAGE }, signal);
        if (mine !== token.current) return;
        setFiles((current) => (offset === 0 ? page.items : [...current, ...page.items]));
        setTotal(page.total);
        setFacets(page.facets);
        setError(null);
      } catch (failure) {
        if (failure?.name !== 'AbortError') setError(failure);
      } finally {
        if (mine === token.current) setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id, query, status, type, sort],
  );

  useEffect(() => {
    const controller = new AbortController();
    api.sources
      .get(id, controller.signal)
      .then(setSource, (failure) => failure?.name !== 'AbortError' && setError(failure));
    // Loading is an external sync: it marks the list busy, then fills it when the API answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(0, controller.signal);
    return () => controller.abort();
  }, [id, load, version]);

  // The next page loads when the end of the list scrolls into view.
  useEffect(() => {
    const node = sentinel.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !loading && files.length < total) load(files.length);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [files.length, total, loading, load]);

  const sortBy = (key) =>
    setSort((current) => ({
      key,
      order: current.key === key && current.order === 'asc' ? 'desc' : 'asc',
    }));
  const running = state?.active === true;
  const index = (mode, target) => start(mode, target ?? source.id);

  const typeNames = Object.keys(facets.type).sort();
  const statusNames = Object.keys(facets.status).sort();

  return (
    <div className={styles.page}>
      <Breadcrumb aria-label="Location">
        <BreadcrumbItem>
          <BreadcrumbButton onClick={() => navigate('/sources')}>Sources</BreadcrumbButton>
        </BreadcrumbItem>
        <BreadcrumbDivider />
        <BreadcrumbItem>
          <BreadcrumbButton current>{source?.name ?? '…'}</BreadcrumbButton>
        </BreadcrumbItem>
      </Breadcrumb>

      {source && (
        <div className={styles.head}>
          <SourceIcon type={source.type} />
          <div className={styles.grow}>
            <Text as="h1" size={500} weight="semibold" block>
              {source.name}
            </Text>
            <Text className={styles.muted}>
              {source.path} · {source.files_processed} of {source.files_total} files ·{' '}
              {formatCredits(source.credits)} credits ·{' '}
              {source.languages ? source.languages.join(', ') : 'default languages'}
            </Text>
          </div>
          <StatusBadge status={source.removed_at ? 'removed' : source.status} />
          <Button
            appearance="primary"
            icon={<Play20Regular />}
            disabled={running || !!source.removed_at}
            onClick={() => index('run')}
          >
            Index now
          </Button>
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <Button>More</Button>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <SourceMenuItems
                  source={source}
                  run={(mode) => index(mode)}
                  onLanguages={() => setLanguages(true)}
                  onRemove={async () => (await actions.remove(source)) && navigate('/sources')}
                  onRestore={() => actions.restore(source)}
                  onPurge={async () => (await actions.purge(source)) && navigate('/sources')}
                />
              </MenuList>
            </MenuPopover>
          </Menu>
        </div>
      )}

      <div className={styles.filters}>
        <Input
          contentBefore={<Search20Regular />}
          placeholder="Search files"
          aria-label="Search files"
          value={query}
          onChange={(_, data) => setQuery(data.value)}
        />
        <Dropdown
          aria-label="File type"
          placeholder="Any type"
          value={type}
          selectedOptions={type ? [type] : []}
          onOptionSelect={(_, data) => setType(data.optionValue ?? '')}
        >
          <Option value="">Any type</Option>
          {typeNames.map((name) => (
            <Option key={name} value={name} text={name}>
              {name} ({facets.type[name]})
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label="File status"
          placeholder="Any status"
          value={status}
          selectedOptions={status ? [status] : []}
          onOptionSelect={(_, data) => setStatus(data.optionValue ?? '')}
        >
          <Option value="">Any status</Option>
          {statusNames.map((name) => (
            <Option key={name} value={name} text={name}>
              {name} ({facets.status[name]})
            </Option>
          ))}
        </Dropdown>
        <Button
          icon={<ArrowDownload20Regular />}
          onClick={() => download(api.sources.filesExportUrl(id, 'csv', filters))}
        >
          Export
        </Button>
        <Text className={styles.muted}>{total} files</Text>
      </div>

      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error.message}</MessageBarBody>
        </MessageBar>
      )}
      <Table aria-label="Files" size="small">
        <TableHeader>
          <TableRow>
            {COLUMNS.map((column) => (
              <TableHeaderCell
                key={column.key}
                sortDirection={
                  sort.key === column.key
                    ? sort.order === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : undefined
                }
                onClick={() => sortBy(column.key)}
              >
                {column.label}
              </TableHeaderCell>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {files.map((file) => {
            const shown = statusOf(file);
            return (
              <Menu key={file.path} openOnContext>
                <MenuTrigger disableButtonEnhancement>
                  <TableRow onDoubleClick={() => setDetails(file)}>
                    <TableCell>
                      <div className={styles.name}>
                        <FileIcon file={file} />
                        <div>
                          <Text block>{file.name}</Text>
                          <Text size={200} className={styles.muted}>
                            {file.relative_path}
                          </Text>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>{file.file_type ?? 'unsupported'}</TableCell>
                    <TableCell>
                      <StatusBadge status={shown.status} title={shown.title} />
                    </TableCell>
                    <TableCell>{formatCredits(file.credits)}</TableCell>
                  </TableRow>
                </MenuTrigger>
                <MenuPopover>
                  <MenuList>
                    <MenuItem icon={<Info20Regular />} onClick={() => setDetails(file)}>
                      Details
                    </MenuItem>
                    <MenuItem
                      icon={<ArrowSync20Regular />}
                      disabled={running || !file.file_type}
                      onClick={() => start('file', file.path)}
                    >
                      Reindex file
                    </MenuItem>
                    <MenuDivider />
                    <MenuItem
                      icon={<Copy20Regular />}
                      onClick={() => navigator.clipboard?.writeText(file.path)}
                    >
                      Copy path
                    </MenuItem>
                    {platform.reveal && (
                      <MenuItem
                        icon={<FolderOpen20Regular />}
                        onClick={() => api.os.reveal(file.path).catch(() => {})}
                      >
                        Show in folder
                      </MenuItem>
                    )}
                  </MenuList>
                </MenuPopover>
              </Menu>
            );
          })}
        </TableBody>
      </Table>
      <div ref={sentinel} />
      {loading && <Spinner size="small" label="Loading files" />}
      {!loading && files.length === 0 && !error && <Text className={styles.muted}>No files.</Text>}
      {!loading && files.length < total && (
        <Button onClick={() => load(files.length)}>Load more</Button>
      )}

      <LanguagesDialog
        source={languages ? source : null}
        onClose={() => setLanguages(false)}
        onSave={async (picked) => {
          setLanguages(false);
          await actions.setLanguages(source, picked);
        }}
      />
      <Dialog open={details !== null} onOpenChange={(_, data) => !data.open && setDetails(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{details?.name}</DialogTitle>
            <DialogContent>
              {details && (
                <div className={styles.detail}>
                  <Text weight="semibold">Path</Text>
                  <Text>{details.path}</Text>
                  <Text weight="semibold">File type</Text>
                  <Text>{details.file_type ?? 'unsupported'}</Text>
                  <Text weight="semibold">Status</Text>
                  <Text>
                    {details.protected ? 'password protected' : (details.status ?? 'pending')}
                  </Text>
                  <Text weight="semibold">Credits</Text>
                  <Text>{formatCredits(details.credits)}</Text>
                  <Text weight="semibold">Size</Text>
                  <Text>{formatBytes(details.size_bytes)}</Text>
                  <Text weight="semibold">Modified</Text>
                  <Text>{formatDate(details.modified_at)}</Text>
                  {details.pages != null && (
                    <>
                      <Text weight="semibold">Pages</Text>
                      <Text>{details.pages}</Text>
                    </>
                  )}
                  {details.confidence != null && (
                    <>
                      <Text weight="semibold">Confidence</Text>
                      <Text>
                        {Math.round(details.confidence * 100)}% {details.band ?? ''}
                      </Text>
                    </>
                  )}
                  {details.error && (
                    <>
                      <Text weight="semibold">Error</Text>
                      <Text>{details.error}</Text>
                    </>
                  )}
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setDetails(null)}>
                Close
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
