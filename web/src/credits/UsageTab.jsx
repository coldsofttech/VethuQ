import {
  Breadcrumb,
  BreadcrumbButton,
  BreadcrumbDivider,
  BreadcrumbItem,
  MessageBar,
  MessageBarBody,
  Text,
} from '@fluentui/react-components';
import { useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { SourceIcon } from '../components/FileIcon.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { formatCredits, formatDate } from '../format.js';
import { ExportMenu, SearchBox, WalletSelect, useFilterStyles } from './Filters.jsx';
import { LoadMore } from './LoadMore.jsx';
import { RANGES, sinceOf } from './labels.js';
import { useInfinite } from './useInfinite.js';

/** Credits per source and, under a source, per file. */
export function UsageTab() {
  const styles = useFilterStyles();
  const [source, setSource] = useState(null); // { id, name } while looking at one source's files
  const [wallet, setWallet] = useState('');
  const [range, setRange] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState({ key: 'credits', order: 'desc' });

  const params = useMemo(
    () => ({
      group_by: source ? 'file' : 'source',
      source: source?.id,
      wallet,
      since: sinceOf(range),
      q,
      sort: sort.key,
      order: sort.order,
    }),
    [source, wallet, range, q, sort],
  );
  const list = useInfinite(
    (offset, signal) => api.credits.usage({ ...params, offset, limit: 200 }, signal),
    [params],
  );
  const toggle = (key) =>
    setSort((s) => ({ key, order: s.key === key && s.order === 'desc' ? 'asc' : 'desc' }));
  const open = (row) => {
    if (!source && row.source_id != null) setSource({ id: row.source_id, name: row.name });
  };

  const columns = [
    {
      key: 'key',
      label: source ? 'File' : 'Source',
      sortable: true,
      render: (r) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {!source && <SourceIcon type="folder" />}
          <span>
            <Text block>{r.name}</Text>
            {source && (
              <Text size={200} className={styles.muted}>
                {r.path}
              </Text>
            )}
          </span>
        </span>
      ),
    },
    {
      key: 'credits',
      label: 'Credits',
      sortable: true,
      align: 'end',
      render: (r) => formatCredits(r.credits),
    },
    { key: 'pages', label: 'Pages', sortable: true, align: 'end' },
    { key: 'last', label: 'Last used', sortable: true, render: (r) => formatDate(r.last_at) },
  ];

  return (
    <div className={styles.page}>
      <Breadcrumb aria-label="Usage level">
        <BreadcrumbItem>
          <BreadcrumbButton current={!source} onClick={() => setSource(null)}>
            All sources
          </BreadcrumbButton>
        </BreadcrumbItem>
        {source && (
          <>
            <BreadcrumbDivider />
            <BreadcrumbItem>
              <BreadcrumbButton current>{source.name}</BreadcrumbButton>
            </BreadcrumbItem>
          </>
        )}
      </Breadcrumb>
      <div className={styles.row}>
        <SearchBox label={source ? 'Search files' : 'Search sources'} value={q} onChange={setQ} />
        <WalletSelect value={wallet} onChange={setWallet} />
        <FilterSelect label="Period" value={range} options={RANGES} onChange={setRange} />
        <span className={styles.grow} />
        <Text className={styles.muted}>{list.total ?? 0} rows</Text>
        <ExportMenu what="usage" params={params} />
      </div>
      {list.error && (
        <MessageBar intent="error">
          <MessageBarBody>{list.error.message}</MessageBarBody>
        </MessageBar>
      )}
      <DataTable
        label={source ? 'Credits per file' : 'Credits per source'}
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.key}
        sort={sort}
        onSort={toggle}
        onRowClick={source ? undefined : open}
      />
      {!list.loading && list.items.length === 0 && (
        <Text className={styles.muted}>
          Nothing was spent here yet. Reading files that need OCR costs credits.
        </Text>
      )}
      <LoadMore more={list.more} loading={list.loading} onMore={list.loadMore} />
    </div>
  );
}
