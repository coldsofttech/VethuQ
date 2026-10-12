import {
  Accordion,
  AccordionHeader,
  AccordionItem,
  AccordionPanel,
  Button,
  MessageBar,
  MessageBarBody,
  Spinner,
  Switch,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { DataTable } from '../components/DataTable.jsx';
import { GroupHeading } from '../components/GroupHeading.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { formatBytes, formatDate } from '../format.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  row: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  muted: { color: tokens.colorNeutralForeground3 },
  facts: {
    display: 'grid',
    gridTemplateColumns: 'max-content 1fr',
    gap: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalXL}`,
  },
  raw: {
    margin: 0,
    maxHeight: '320px',
    overflow: 'auto',
    padding: tokens.spacingVerticalM,
    background: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
  },
});

const SEND_WORDS = {
  sent: 'Sent.',
  not_opted_in: 'Sharing is off, so nothing was sent.',
  disabled: 'Sending is not allowed right now.',
  nothing_to_do: 'Nothing to send, or already tried today.',
  failed: 'Could not send.',
};

function Facts({ rows }) {
  const styles = useStyles();
  return (
    <div className={styles.facts}>
      {rows.map(([label, value]) => (
        <span key={label} style={{ display: 'contents' }}>
          <Text className={styles.muted}>{label}</Text>
          <Text>{String(value)}</Text>
        </span>
      ))}
    </div>
  );
}

const ROW_COLUMNS = [
  { key: 'file_type', label: 'File type' },
  { key: 'page_source', label: 'How read' },
  { key: 'phase', label: 'Phase', render: (r) => r.phase || '—' },
  { key: 'engine', label: 'Engine', render: (r) => r.engine || '—' },
  { key: 'language', label: 'Language' },
  { key: 'size_bucket', label: 'Page size' },
  { key: 'band', label: 'Confidence', render: (r) => r.band || '—' },
  { key: 'pages', label: 'Pages', align: 'end' },
  { key: 'passes', label: 'Passes', align: 'end' },
  { key: 'duration_ms', label: 'Time (ms)', align: 'end' },
  { key: 'credits_milli', label: 'Credits (milli)', align: 'end' },
];

const FAILURE_COLUMNS = [
  { key: 'file_type', label: 'File type' },
  { key: 'code', label: 'Reason' },
  { key: 'count', label: 'Files', align: 'end' },
];

const pagesOf = (day) => day.pages.reduce((sum, r) => sum + r.pages, 0);

/** Whether sharing is on, exactly what would be sent next, and sending or deleting. */
export function MetricsPanel({ reloadKey }) {
  const styles = useStyles();
  const notify = useNotify();
  const [status, setStatus] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [raw, setRaw] = useState(false);
  const [busy, setBusy] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [count, setCount] = useState(0);
  const reload = useCallback(() => setCount((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.maintenance.metrics(controller.signal),
      api.maintenance.metricsPreview(controller.signal),
    ]).then(
      ([s, p]) => {
        setStatus(s);
        setPreview(p);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [count, reloadKey]);

  const send = async () => {
    setBusy('send');
    try {
      const result = await api.maintenance.metricsSend(true);
      notify({
        title: SEND_WORDS[result.status] ?? result.status,
        body: result.status === 'failed' ? result.detail : undefined,
        intent:
          result.status === 'sent' ? 'success' : result.status === 'failed' ? 'error' : 'info',
      });
      reload();
    } catch (failure) {
      notify({ title: 'Could not send', body: failure.message, intent: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setDeleting(false);
    setBusy('delete');
    try {
      const result = await api.maintenance.metricsDelete();
      notify({
        title: result.status === 'sent' ? 'Deletion requested' : 'Could not request deletion',
        body: result.detail || undefined,
        intent: result.status === 'sent' ? 'success' : 'warning',
      });
      reload();
    } catch (failure) {
      notify({ title: 'Could not request deletion', body: failure.message, intent: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(preview.batch, null, 2));
      notify({ title: 'Copied' });
    } catch {
      notify({ title: 'Could not copy', intent: 'warning' });
    }
  };

  if (error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!status || !preview) return <Spinner size="small" label="Loading" />;

  const batch = preview.batch;
  return (
    <div className={styles.root}>
      <GroupHeading
        title="What is shared"
        note="Counts and sizes only: no file names, paths, text or anything that identifies you. This is exactly what would be sent next."
      />
      <Facts
        rows={[
          ['Sharing', status.opted_in ? 'On' : 'Off'],
          ['Sending allowed', status.available ? 'Yes' : 'Not right now'],
          ['Last sent', status.last_sent_at ? formatDate(status.last_sent_at) : 'Never'],
          ['Sent through', status.sent_through ?? '—'],
          ['Days waiting to be sent', status.pending_days],
          [
            'Credits bonus',
            status.bonus_active
              ? `On (+${status.bonus_percent}%)`
              : `Off (it would be +${status.bonus_percent}%)`,
          ],
        ]}
      />
      <div className={styles.row}>
        <Button disabled={busy !== null || !status.opted_in || !status.available} onClick={send}>
          {busy === 'send' ? <Spinner size="tiny" /> : 'Send now'}
        </Button>
        <Button disabled={busy !== null || !status.available} onClick={() => setDeleting(true)}>
          {busy === 'delete' ? <Spinner size="tiny" /> : 'Delete my data…'}
        </Button>
        <Text className={styles.muted}>Next batch: {formatBytes(preview.size_bytes)}</Text>
      </div>
      <Text weight="semibold">Your install</Text>
      <Facts
        rows={[
          ['Anonymous install id', batch.install_id],
          ['Batch id', batch.batch_id],
          ...Object.entries(batch.client).map(([key, value]) => [
            `Computer: ${key.replace(/_/g, ' ')}`,
            value,
          ]),
          ...Object.entries(batch.settings).map(([key, value]) => [
            `Setting: ${key.replace(/_/g, ' ')}`,
            Array.isArray(value) ? value.join(', ') : value,
          ]),
        ]}
      />
      <Text weight="semibold">Usage, by day</Text>
      {batch.days.length === 0 ? (
        <Text className={styles.muted}>Nothing is waiting to be sent.</Text>
      ) : (
        <Accordion collapsible multiple>
          {batch.days.map((day) => (
            <AccordionItem key={day.day} value={day.day}>
              <AccordionHeader>
                {day.day} · {pagesOf(day)} pages in {day.pages.length} groups
                {day.failures?.length ? ` · ${day.failures.length} failure groups` : ''}
              </AccordionHeader>
              <AccordionPanel>
                <DataTable
                  label={`Usage on ${day.day}`}
                  columns={ROW_COLUMNS}
                  rows={day.pages}
                  rowKey={(r) => JSON.stringify(r)}
                />
                {day.failures?.length > 0 && (
                  <DataTable
                    label={`Failures on ${day.day}`}
                    columns={FAILURE_COLUMNS}
                    rows={day.failures}
                    rowKey={(r) => `${r.file_type}-${r.code}`}
                  />
                )}
              </AccordionPanel>
            </AccordionItem>
          ))}
        </Accordion>
      )}
      <div className={styles.row}>
        <Switch label="Show the raw data" checked={raw} onChange={(_, d) => setRaw(d.checked)} />
        <Button size="small" onClick={copy}>
          Copy
        </Button>
      </div>
      {raw && (
        <pre className={styles.raw} aria-label="Raw batch">
          {JSON.stringify(batch, null, 2)}
        </pre>
      )}
      <ConfirmDialog
        open={deleting}
        title="Delete the data already sent?"
        confirmLabel="Delete"
        onConfirm={remove}
        onCancel={() => setDeleting(false)}
      >
        VethuQ asks the collector to delete everything it holds for this install, and starts with a
        new anonymous id. Sharing stays as it is.
      </ConfirmDialog>
    </div>
  );
}
