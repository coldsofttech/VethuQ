import { MessageBar, MessageBarBody, Spinner, Text } from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { formatBytes, formatCredits, formatDate } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

/** The jobs sent to GitHub for OCR, newest first. */
export function JobsTab() {
  const { version } = useIndexing();
  const [state, setState] = useState({ jobs: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    api.github.jobs(controller.signal).then(
      (data) => setState({ jobs: data.jobs, error: null }),
      (error) => error?.name !== 'AbortError' && setState({ jobs: null, error }),
    );
    return () => controller.abort();
  }, [version]);

  if (state.error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{state.error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!state.jobs) return <Spinner size="small" label="Loading jobs" />;
  if (state.jobs.length === 0)
    return <Text>No jobs yet. They appear when a run sends pages to GitHub for OCR.</Text>;

  const columns = [
    { key: 'id', label: 'Job' },
    { key: 'run_id', label: 'Run', render: (j) => j.run_id ?? '—' },
    {
      key: 'status',
      label: 'Status',
      render: (j) => <StatusBadge status={j.status} title={j.error ?? undefined} />,
    },
    { key: 'images', label: 'Pages', align: 'end' },
    { key: 'size_bytes', label: 'Size', align: 'end', render: (j) => formatBytes(j.size_bytes) },
    { key: 'credits', label: 'Credits', align: 'end', render: (j) => formatCredits(j.credits) },
    { key: 'submitted_at', label: 'Sent', render: (j) => formatDate(j.submitted_at) },
    { key: 'completed_at', label: 'Done', render: (j) => formatDate(j.completed_at) },
    { key: 'error', label: 'Problem', render: (j) => j.error ?? '' },
  ];
  return <DataTable label="GitHub jobs" columns={columns} rows={state.jobs} rowKey={(j) => j.id} />;
}
