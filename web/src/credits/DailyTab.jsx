import { MessageBar, MessageBarBody, Spinner, Text } from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { formatCredits, formatDay } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { BarChart } from './BarChart.jsx';
import { useFilterStyles } from './Filters.jsx';
import { walletLabel } from './labels.js';

const SPANS = [
  { value: '14', label: 'Last 14 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
];

export function DailyTab() {
  const styles = useFilterStyles();
  const { version } = useIndexing();
  const [span, setSpan] = useState('30');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    api.credits.daily(span, controller.signal).then(
      (result) => {
        setData(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [span, version]);

  if (error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!data) return <Spinner size="small" label="Loading" />;

  const rows = [...data.days].reverse().map((day) => ({
    ...day,
    total: data.wallets.reduce((sum, w) => sum + Number(day[w] || 0), 0),
  }));
  const columns = [
    { key: 'day', label: 'Day (UTC)', render: (r) => formatDay(r.day) },
    ...data.wallets.map((w) => ({
      key: w,
      label: walletLabel(w),
      align: 'end',
      render: (r) => formatCredits(r[w]),
    })),
    { key: 'total', label: 'Total', align: 'end', render: (r) => formatCredits(r.total) },
  ];
  const sum = rows.reduce((total, r) => total + r.total, 0);

  return (
    <div className={styles.page}>
      <div className={styles.row}>
        <FilterSelect
          label="Period"
          value={span}
          options={SPANS}
          onChange={(v) => setSpan(v || '30')}
        />
        <span className={styles.grow} />
        <Text className={styles.muted}>{formatCredits(sum)} credits in this period</Text>
      </div>
      <BarChart days={data.days} series={data.wallets} />
      <DataTable label="Credits per day" columns={columns} rows={rows} rowKey={(r) => r.day} />
    </div>
  );
}
