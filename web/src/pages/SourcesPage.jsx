import {
  Button,
  Checkbox,
  Dropdown,
  Input,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  SplitButton,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Toolbar,
  ToolbarDivider,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowSync20Regular,
  DocumentAdd20Regular,
  FolderAdd20Regular,
  Pause20Regular,
  Play20Regular,
  Search20Regular,
  Stop20Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { SourceIcon } from '../components/FileIcon.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { download, formatDate } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { AddPathDialog } from '../sources/AddPathDialog.jsx';
import { LanguagesDialog } from '../sources/LanguagesDialog.jsx';
import { SourceMenuItems } from '../sources/SourceMenuItems.jsx';
import { useAdd } from '../sources/useAdd.js';
import { useSourceActions } from '../sources/useSourceActions.js';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  toolbar: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
  },
  filters: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: tokens.spacingHorizontalM,
  },
  row: { cursor: 'pointer' },
  name: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, minWidth: 0 },
  parent: { color: tokens.colorNeutralForeground3 },
  empty: {
    color: tokens.colorNeutralForeground2,
    padding: tokens.spacingVerticalXXL,
    textAlign: 'center',
  },
});

const STATUSES = ['pending', 'in_progress', 'completed', 'error'];
const COLUMNS = [
  { key: 'name', label: 'Name' },
  { key: 'status', label: 'Status' },
  { key: 'files_processed', label: 'Files' },
  { key: 'languages', label: 'Languages' },
  { key: 'added_at', label: 'Added' },
  { key: 'last_scanned_at', label: 'Last scanned' },
];
const SORTABLE = new Set(['name', 'status', 'added_at', 'last_scanned_at']);

export function SourcesPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { state, version, start, pause, resume, requestStop, refresh } = useIndexing();
  const actions = useSourceActions();
  const add = useAdd();

  const [rows, setRows] = useState(
    /** @type {import('../api/client.js').SourceRow[] | null} */ (null),
  );
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(/** @type {number | null} */ (null));
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [removed, setRemoved] = useState(false);
  const [sort, setSort] = useState({ key: 'id', order: 'asc' });
  const [languages, setLanguages] = useState(null);
  const [confirm, setConfirm] = useState(
    /** @type {{ kind: 'remove' | 'purge' | 'all', source?: any } | null} */ (null),
  );
  const loaded = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const token = ++loaded.current;
    api.sources
      .list({ q: query, status, removed, sort: sort.key, order: sort.order }, controller.signal)
      .then(
        (data) => {
          if (token === loaded.current) {
            setRows(data.sources);
            setError(null);
          }
        },
        (failure) => failure?.name !== 'AbortError' && setError(failure),
      );
    return () => controller.abort();
  }, [query, status, removed, sort, version]);

  const sortBy = (key) =>
    setSort((current) => ({
      key,
      order: current.key === key && current.order === 'asc' ? 'desc' : 'asc',
    }));
  const selectedRow = rows?.find((row) => row.id === selected) ?? null;
  const running = state?.active === true;
  const run = useCallback((mode, source) => start(mode, source ? source.id : null), [start]);

  const confirmed = async () => {
    const { kind, source } = confirm;
    setConfirm(null);
    if (kind === 'remove') await actions.remove(source);
    else if (kind === 'purge') await actions.purge(source);
    else await start('run', null);
  };

  const exportSources = (format) => download(api.sources.exportUrl(format, { removed }));

  return (
    <div className={styles.page}>
      <PageHeader title="Sources" lead="The folders and files that VethuQ reads." />
      <Toolbar className={styles.toolbar} aria-label="Sources">
        <Button icon={<FolderAdd20Regular />} onClick={() => add.pick('folder')}>
          Add folder
        </Button>
        <Button icon={<DocumentAdd20Regular />} onClick={() => add.pick('file')}>
          Add file
        </Button>
        <ToolbarDivider />
        <Menu positioning="below-end">
          <MenuTrigger disableButtonEnhancement>
            {(triggerProps) => (
              <SplitButton
                icon={<Play20Regular />}
                disabled={running}
                menuButton={triggerProps}
                primaryActionButton={{ onClick: () => run('run', selectedRow) }}
              >
                {selectedRow ? 'Index selected' : 'Index'}
              </SplitButton>
            )}
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem onClick={() => run('run', selectedRow)}>New and changed files</MenuItem>
              <MenuItem onClick={() => run('restart', selectedRow)}>Retry failed files</MenuItem>
              <MenuItem disabled={!selectedRow} onClick={() => run('reindex', selectedRow)}>
                Reindex everything
              </MenuItem>
              <MenuItem onClick={() => setConfirm({ kind: 'all' })}>Index all sources</MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
        {running && (
          <>
            <Button
              icon={state.paused ? <Play20Regular /> : <Pause20Regular />}
              onClick={state.paused ? resume : pause}
            >
              {state.paused ? 'Resume' : 'Pause'}
            </Button>
            <Button icon={<Stop20Regular />} disabled={state.stopping} onClick={requestStop}>
              Stop
            </Button>
          </>
        )}
        <ToolbarDivider />
        <Button icon={<ArrowSync20Regular />} onClick={refresh}>
          Refresh
        </Button>
        <Menu>
          <MenuTrigger disableButtonEnhancement>
            <Button icon={<ArrowDownload20Regular />}>Export</Button>
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem onClick={() => exportSources('csv')}>As CSV</MenuItem>
              <MenuItem onClick={() => exportSources('json')}>As JSON</MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
      </Toolbar>

      <div className={styles.filters}>
        <Input
          contentBefore={<Search20Regular />}
          placeholder="Search sources"
          aria-label="Search sources"
          value={query}
          onChange={(_, data) => setQuery(data.value)}
        />
        <Dropdown
          aria-label="Status"
          placeholder="Any status"
          value={status ? status.replace('_', ' ') : ''}
          selectedOptions={status ? [status] : []}
          onOptionSelect={(_, data) => setStatus(data.optionValue ?? '')}
        >
          <Option value="">Any status</Option>
          {STATUSES.map((item) => (
            <Option key={item} value={item}>
              {item.replace('_', ' ')}
            </Option>
          ))}
        </Dropdown>
        <Checkbox
          label="Show removed"
          checked={removed}
          onChange={(_, data) => setRemoved(data.checked === true)}
        />
      </div>

      {error && (
        <MessageBar intent="error">
          <MessageBarBody>Could not load the sources: {error.message}</MessageBarBody>
        </MessageBar>
      )}
      {rows === null && !error && <Spinner size="small" label="Loading sources" />}
      {rows?.length === 0 && (
        <Text className={styles.empty}>
          {query || status
            ? 'No source matches.'
            : 'No sources yet. Add a folder or drop one here.'}
        </Text>
      )}
      {rows?.length > 0 && (
        <Table aria-label="Sources" size="small">
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
                  onClick={SORTABLE.has(column.key) ? () => sortBy(column.key) : undefined}
                >
                  {column.label}
                </TableHeaderCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((source) => (
              <Menu key={source.id} openOnContext>
                <MenuTrigger disableButtonEnhancement>
                  <TableRow
                    className={styles.row}
                    aria-selected={selected === source.id}
                    appearance={selected === source.id ? 'brand' : 'none'}
                    onClick={() => setSelected(source.id)}
                    onDoubleClick={() => !source.removed_at && navigate(`/sources/${source.id}`)}
                  >
                    <TableCell>
                      <div className={styles.name}>
                        <SourceIcon type={source.type} />
                        <div>
                          <Text block weight="semibold">
                            {source.name}
                          </Text>
                          <Text size={200} className={styles.parent}>
                            {source.missing ? 'Not found on disk · ' : ''}
                            {source.parent}
                          </Text>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={source.removed_at ? 'removed' : source.status} />
                    </TableCell>
                    <TableCell>
                      {source.files_processed} of {source.files_total}
                    </TableCell>
                    <TableCell>
                      {source.languages ? source.languages.join(', ') : 'Default'}
                    </TableCell>
                    <TableCell>{formatDate(source.added_at)}</TableCell>
                    <TableCell>{formatDate(source.last_scanned_at)}</TableCell>
                  </TableRow>
                </MenuTrigger>
                <MenuPopover>
                  <MenuList>
                    <SourceMenuItems
                      source={source}
                      run={(mode) => run(mode, source)}
                      onOpen={() => navigate(`/sources/${source.id}`)}
                      onLanguages={() => setLanguages(source)}
                      onRemove={() => setConfirm({ kind: 'remove', source })}
                      onRestore={() => actions.restore(source)}
                      onPurge={() => setConfirm({ kind: 'purge', source })}
                    />
                  </MenuList>
                </MenuPopover>
              </Menu>
            ))}
          </TableBody>
        </Table>
      )}

      <AddPathDialog kind={add.typing} onAdd={add.typed} onClose={add.closeTyping} />
      <LanguagesDialog
        source={languages}
        onClose={() => setLanguages(null)}
        onSave={async (picked) => {
          const source = languages;
          setLanguages(null);
          await actions.setLanguages(source, picked);
        }}
      />
      <ConfirmDialog
        open={confirm !== null}
        title={
          confirm?.kind === 'all'
            ? 'Index all sources?'
            : confirm?.kind === 'purge'
              ? `Delete ${confirm.source.name} for good?`
              : `Remove ${confirm?.source?.name}?`
        }
        confirmLabel={
          confirm?.kind === 'all' ? 'Index all' : confirm?.kind === 'purge' ? 'Delete' : 'Remove'
        }
        onConfirm={confirmed}
        onCancel={() => setConfirm(null)}
      >
        {confirm?.kind === 'all'
          ? 'Every source is read in turn. New and changed files are indexed.'
          : confirm?.kind === 'purge'
            ? 'Its indexed pages and its history are deleted. The files on disk stay.'
            : 'Its files leave the search results. The files on disk stay, and you can restore it later.'}
      </ConfirmDialog>
    </div>
  );
}
