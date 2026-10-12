import {
  Button,
  MessageBar,
  MessageBarBody,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload20Regular, Open16Regular } from '@fluentui/react-icons';
import { Menu, MenuItem, MenuList, MenuPopover, MenuTrigger } from '@fluentui/react-components';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { LoadMore } from '../credits/LoadMore.jsx';
import { useInfinite } from '../credits/useInfinite.js';
import { download, formatCredits, formatDuration } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { GROUP_LABELS, NARROWS, toParams } from './filters.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  row: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  grow: { flexGrow: 1 },
  muted: { color: tokens.colorNeutralForeground3 },
  total: { fontWeight: tokens.fontWeightSemibold },
});

const GROUPS = Object.entries(GROUP_LABELS).map(([value, label]) => ({ value, label }));
const TOTAL = '__total';

const percent = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`);

export function BreakdownTab({ filters, onNarrow, refresh }) {
  const styles = useStyles();
  const navigate = useNavigate();
  const { version } = useIndexing();
  const [group, setGroup] = useState('source');
  const [sort, setSort] = useState({ key: 'pages', order: 'desc' });

  const params = useMemo(
    () => ({ ...toParams(filters), group_by: group, sort: sort.key, order: sort.order }),
    [filters, group, sort],
  );
  const list = useInfinite(
    (offset, signal) => api.stats.breakdown({ ...params, offset, limit: 100 }, signal),
    [params, version, refresh],
  );
  const toggle = (key) =>
    setSort((s) => ({ key, order: s.key === key && s.order === 'desc' ? 'asc' : 'desc' }));

  // The totals of everything the filters keep sit at the top of the table.
  const totals = list.meta?.totals;
  const rows = useMemo(
    () => (totals ? [{ ...totals, key: TOTAL }, ...list.items] : list.items),
    [list.items, totals],
  );

  const narrow = (row) => {
    if (row.key === TOTAL) return;
    const value = group === 'source' && row.source_id != null ? String(row.source_id) : row.key;
    onNarrow(NARROWS[group], value);
  };

  const columns = [
    {
      key: 'key',
      label: GROUP_LABELS[group],
      sortable: true,
      render: (r) =>
        r.key === TOTAL ? (
          <span className={styles.total}>Total</span>
        ) : (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title={r.key}>
            {r.name ?? r.key}
            {group === 'source' && r.source_id != null && (
              <Tooltip content="Open source" relationship="label">
                <Button
                  size="small"
                  appearance="subtle"
                  icon={<Open16Regular />}
                  onClick={(event) => {
                    event.stopPropagation();
                    navigate(`/sources/${r.source_id}`);
                  }}
                />
              </Tooltip>
            )}
          </span>
        ),
    },
    ...(group === 'source'
      ? [
          {
            key: 'files',
            label: 'Files',
            sortable: true,
            align: 'end',
            render: (r) => r.files ?? '—',
          },
        ]
      : []),
    {
      key: 'pages',
      label: 'Pages',
      sortable: true,
      align: 'end',
      render: (r) => r.pages.toLocaleString(),
    },
    {
      key: 'native_pages',
      label: 'Native',
      align: 'end',
      render: (r) => r.native_pages.toLocaleString(),
    },
    {
      key: 'ocr_pages',
      label: 'OCR',
      sortable: true,
      align: 'end',
      render: (r) => r.ocr_pages.toLocaleString(),
    },
    {
      key: 'confidence',
      label: 'Confidence',
      sortable: true,
      align: 'end',
      render: (r) => percent(r.confidence),
    },
    {
      key: 'duration_ms',
      label: 'OCR time',
      sortable: true,
      align: 'end',
      render: (r) => (r.duration_ms ? formatDuration(r.duration_ms / 1000) : '—'),
    },
    {
      key: 'pages_per_minute',
      label: 'Pages a minute',
      align: 'end',
      render: (r) => (r.pages_per_minute ? r.pages_per_minute.toFixed(1) : '—'),
    },
    {
      key: 'credits',
      label: 'Credits',
      sortable: true,
      align: 'end',
      render: (r) => formatCredits(r.credits),
    },
    {
      key: 'failures',
      label: 'Failures',
      sortable: true,
      align: 'end',
      render: (r) => r.failures ?? '—',
    },
  ];

  return (
    <div className={styles.root}>
      <div className={styles.row}>
        <FilterSelect
          label="Group by"
          value={group}
          options={GROUPS}
          onChange={(v) => setGroup(v || 'source')}
        />
        <span className={styles.grow} />
        <Text className={styles.muted}>Click a row to narrow the statistics to it</Text>
        <Menu>
          <MenuTrigger disableButtonEnhancement>
            <ToolButton label="Export" icon={<ArrowDownload20Regular />} />
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem onClick={() => download(api.stats.exportUrl('csv', params))}>
                As CSV
              </MenuItem>
              <MenuItem onClick={() => download(api.stats.exportUrl('json', params))}>
                As JSON
              </MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
      </div>
      {list.error && (
        <MessageBar intent="error">
          <MessageBarBody>{list.error.message}</MessageBarBody>
        </MessageBar>
      )}
      <DataTable
        label="Breakdown"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        sort={sort}
        onSort={toggle}
        onRowClick={narrow}
      />
      {!list.loading && list.items.length === 0 && (
        <Text className={styles.muted}>Nothing has been read for these filters.</Text>
      )}
      <LoadMore more={list.more} loading={list.loading} onMore={list.loadMore} />
    </div>
  );
}
