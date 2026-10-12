import { MessageBar, MessageBarBody, Text, mergeClasses } from '@fluentui/react-components';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { formatCredits, formatDate } from '../format.js';
import { ExportMenu, WalletSelect, useFilterStyles } from './Filters.jsx';
import { LoadMore } from './LoadMore.jsx';
import { ENTRY_LABELS, RANGES, signedAmount, sinceOf, walletLabel } from './labels.js';
import { useInfinite } from './useInfinite.js';

const KINDS = [
  { value: '', label: 'All movements' },
  ...Object.entries(ENTRY_LABELS).map(([value, label]) => ({ value, label })),
];

function useSourceOptions() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let live = true;
    api.sources.list({ removed: true }).then(
      (data) => live && setRows(data.sources),
      () => {},
    );
    return () => {
      live = false;
    };
  }, []);
  return [
    { value: '', label: 'All sources' },
    ...rows.map((s) => ({ value: String(s.id), label: s.name })),
  ];
}

export function LedgerTab() {
  const styles = useFilterStyles();
  const [kind, setKind] = useState('');
  const [wallet, setWallet] = useState('');
  const [range, setRange] = useState('30');
  const [source, setSource] = useState('');
  const [sort, setSort] = useState({ key: 'at', order: 'desc' });
  const sources = useSourceOptions();

  const params = useMemo(
    () => ({ kind, wallet, source, since: sinceOf(range), sort: sort.key, order: sort.order }),
    [kind, wallet, source, range, sort],
  );
  const list = useInfinite(
    (offset, signal) => api.credits.ledger({ ...params, offset, limit: 100 }, signal),
    [params],
  );
  const toggle = (key) =>
    setSort((s) => ({ key, order: s.key === key && s.order === 'desc' ? 'asc' : 'desc' }));

  const columns = [
    { key: 'at', label: 'Time', sortable: true, render: (e) => formatDate(e.at) },
    { key: 'wallet', label: 'Wallet', render: (e) => walletLabel(e.wallet) },
    {
      key: 'kind',
      label: 'Movement',
      sortable: true,
      render: (e) => ENTRY_LABELS[e.kind] ?? e.kind,
    },
    {
      key: 'amount',
      label: 'Credits',
      sortable: true,
      align: 'end',
      render: (e) => {
        const value = signedAmount(e);
        return (
          <span className={mergeClasses(value < 0 ? styles.amountOut : styles.amountIn)}>
            {value > 0 ? '+' : ''}
            {formatCredits(value)}
          </span>
        );
      },
    },
    { key: 'file', label: 'File or note', render: (e) => e.file ?? e.note ?? '—' },
    { key: 'page_number', label: 'Page', align: 'end', render: (e) => e.page_number ?? '—' },
    { key: 'phase', label: 'Phase', render: (e) => e.phase ?? '—' },
    { key: 'language', label: 'Language', render: (e) => e.language ?? '—' },
    { key: 'run_id', label: 'Run', align: 'end', render: (e) => e.run_id ?? '—' },
  ];

  return (
    <div className={styles.page}>
      <div className={styles.row}>
        <FilterSelect label="Movement" value={kind} options={KINDS} onChange={setKind} />
        <WalletSelect value={wallet} onChange={setWallet} />
        <FilterSelect label="Source" value={source} options={sources} onChange={setSource} />
        <FilterSelect label="Period" value={range} options={RANGES} onChange={setRange} />
        <span className={styles.grow} />
        <ExportMenu what="ledger" params={params} />
      </div>
      {list.error && (
        <MessageBar intent="error">
          <MessageBarBody>{list.error.message}</MessageBarBody>
        </MessageBar>
      )}
      <DataTable
        label="Ledger"
        columns={columns}
        rows={list.items}
        rowKey={(e) => e.id}
        sort={sort}
        onSort={toggle}
      />
      {!list.loading && list.items.length === 0 && (
        <Text className={styles.muted}>No movements match.</Text>
      )}
      <LoadMore more={list.more} loading={list.loading} onMore={list.loadMore} />
    </div>
  );
}
