import { Checkbox, MessageBar, MessageBarBody, Text } from '@fluentui/react-components';
import { useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { formatCredits, formatDate } from '../format.js';
import { ExportMenu, SearchBox, WalletSelect, useFilterStyles } from './Filters.jsx';
import { LoadMore } from './LoadMore.jsx';
import { KIND_LABELS, walletLabel } from './labels.js';
import { useInfinite } from './useInfinite.js';

const KINDS = [
  { value: '', label: 'All kinds' },
  ...Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label })),
];

export function GrantsTab() {
  const styles = useFilterStyles();
  const [wallet, setWallet] = useState('');
  const [kind, setKind] = useState('');
  const [lapsed, setLapsed] = useState(true);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState({ key: 'granted_at', order: 'desc' });

  const params = useMemo(
    () => ({ wallet, kind, q, expired: lapsed ? '1' : '0', sort: sort.key, order: sort.order }),
    [wallet, kind, q, lapsed, sort],
  );
  const list = useInfinite(
    (offset, signal) => api.credits.grants({ ...params, offset, limit: 200 }, signal),
    [params],
  );
  const toggle = (key) =>
    setSort((s) => ({ key, order: s.key === key && s.order === 'desc' ? 'asc' : 'desc' }));

  const columns = [
    {
      key: 'granted_at',
      label: 'Granted',
      sortable: true,
      render: (g) => formatDate(g.granted_at),
    },
    { key: 'wallet', label: 'Wallet', render: (g) => walletLabel(g.wallet) },
    { key: 'kind', label: 'Type', sortable: true, render: (g) => KIND_LABELS[g.kind] ?? g.kind },
    { key: 'name', label: 'Name', sortable: true },
    { key: 'scope', label: 'Applies to', render: (g) => g.scope ?? 'All work' },
    {
      key: 'amount',
      label: 'Amount',
      sortable: true,
      align: 'end',
      render: (g) => formatCredits(g.amount),
    },
    {
      key: 'used',
      label: 'Used',
      sortable: true,
      align: 'end',
      render: (g) => formatCredits(g.used),
    },
    {
      key: 'remaining',
      label: 'Left',
      sortable: true,
      align: 'end',
      render: (g) =>
        g.expired ? `${formatCredits(g.remaining)} (lapsed)` : formatCredits(g.remaining),
    },
    {
      key: 'expires_at',
      label: 'Expires',
      sortable: true,
      render: (g) => (g.expires_at ? formatDate(g.expires_at) : 'Never'),
    },
  ];

  return (
    <div className={styles.page}>
      <div className={styles.row}>
        <SearchBox label="Search grants" value={q} onChange={setQ} />
        <WalletSelect value={wallet} onChange={setWallet} />
        <FilterSelect label="Kind" value={kind} options={KINDS} onChange={setKind} />
        <Checkbox
          label="Show lapsed"
          checked={lapsed}
          onChange={(_, d) => setLapsed(d.checked === true)}
        />
        <span className={styles.grow} />
        <Text className={styles.muted}>{list.total ?? 0} grants</Text>
        <ExportMenu what="grants" params={params} />
      </div>
      {list.error && (
        <MessageBar intent="error">
          <MessageBarBody>{list.error.message}</MessageBarBody>
        </MessageBar>
      )}
      <DataTable
        label="Grants"
        columns={columns}
        rows={list.items}
        rowKey={(g) => g.id}
        sort={sort}
        onSort={toggle}
      />
      {!list.loading && list.items.length === 0 && (
        <Text className={styles.muted}>No grants match.</Text>
      )}
      <LoadMore more={list.more} loading={list.loading} onMore={list.loadMore} />
    </div>
  );
}
