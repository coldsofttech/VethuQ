import {
  Button,
  MessageBar,
  MessageBarBody,
  ProgressBar,
  Spinner,
  Tab,
  TabList,
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
  ArrowSync20Regular,
  Dismiss20Regular,
  Pause20Regular,
  Play20Regular,
  Stop20Regular,
} from '@fluentui/react-icons';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { ToolButton } from '../components/ToolButton.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { ServiceDot } from '../components/ServiceDot.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { baseName, formatBytes, formatCredits, formatDate, formatDuration } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalL,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
  },
  muted: { color: tokens.colorNeutralForeground3 },
  stats: { display: 'flex', gap: tokens.spacingHorizontalXXL, flexWrap: 'wrap' },
});

const TABS = [
  { value: 'activity', label: 'Activity' },
  { value: 'history', label: 'History' },
  { value: 'jobs', label: 'Remote jobs' },
  { value: 'queue', label: 'Queue' },
];

const RUNNERS = {
  idle: 'Nothing is running',
  'one-off': 'Running in this application',
  service: 'Running in the background service',
  external: 'Running in another process',
};

function Stat({ label, value }) {
  const styles = useStyles();
  return (
    <div>
      <Text block size={600} weight="semibold">
        {value}
      </Text>
      <Text className={styles.muted}>{label}</Text>
    </div>
  );
}

function Activity() {
  const styles = useStyles();
  const { state, pause, resume, requestStop } = useIndexing();
  if (!state) return <Spinner size="small" />;
  const run = state.run;
  const live = state.active;
  const total = run?.files_total || 0;
  return (
    <div className={styles.card}>
      <Text weight="semibold">{RUNNERS[state.runner.mode] ?? state.runner.mode}</Text>
      {state.service && (
        <div className={styles.bar} data-testid="service-status">
          <ServiceDot colour={state.service.colour} aria-hidden="true" />
          <Text>Background service: {state.service.label}</Text>
        </div>
      )}
      {state.error && (
        <MessageBar intent="error">
          <MessageBarBody>{state.error}</MessageBarBody>
        </MessageBar>
      )}
      {state.queued > 0 && (
        <Text>
          {state.queued} request{state.queued === 1 ? '' : 's'} waiting in the queue.
        </Text>
      )}
      {state.waiting_credits?.length > 0 && (
        <MessageBar intent="warning">
          <MessageBarBody>
            {state.waiting_credits.length} request{state.waiting_credits.length === 1 ? '' : 's'}{' '}
            waiting for credits; the background service takes them up again at{' '}
            {formatDate(state.waiting_credits[0].resume_at)}.
          </MessageBarBody>
        </MessageBar>
      )}
      {run ? (
        <>
          <div className={styles.bar}>
            <Text className={styles.grow}>
              {run.target ? baseName(run.target) : 'All sources'} · started{' '}
              {formatDate(run.started_at)}
            </Text>
            <StatusBadge status={state.paused ? 'stopped' : run.status} />
          </div>
          <ProgressBar value={total ? run.files_processed / total : undefined} />
          <div className={styles.stats}>
            <Stat label="Files done" value={`${run.files_processed} of ${total}`} />
            <Stat label="Failed" value={run.files_failed} />
            <Stat label="Pages" value={run.pages_processed} />
            <Stat label="OCR pages" value={run.ocr_pages} />
            <Stat label="Credits" value={formatCredits(run.credits_charged)} />
            {live && state.eta?.seconds > 0 && (
              <Stat label="Time left" value={formatDuration(state.eta.seconds)} />
            )}
          </div>
          {state.current_files.length > 0 && (
            <div>
              <Text className={styles.muted} block>
                Reading now
              </Text>
              {state.current_files.map((path) => (
                <Text key={path} block>
                  {baseName(path)}
                </Text>
              ))}
            </div>
          )}
          {run.error && <Text>{run.error}</Text>}
          {live && (
            <div className={styles.bar}>
              <ToolButton
                label={state.paused ? 'Resume' : 'Pause'}
                icon={state.paused ? <Play20Regular /> : <Pause20Regular />}
                onClick={state.paused ? resume : pause}
              />
              <ToolButton
                label="Stop"
                icon={<Stop20Regular />}
                disabled={state.stopping}
                onClick={requestStop}
              />
            </div>
          )}
        </>
      ) : (
        <Text className={styles.muted}>No run yet. Start one from Sources.</Text>
      )}
    </div>
  );
}

/** A table that loads from the API again whenever lists on screen should. */
function Listing({ load, columns, row, empty, label }) {
  const { version } = useIndexing();
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (list) => {
        setItems(list);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [load, version]);
  if (error) {
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  }
  if (items === null) return <Spinner size="small" />;
  if (items.length === 0) return <Text>{empty}</Text>;
  return (
    <Table aria-label={label} size="small">
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHeaderCell key={column}>{column}</TableHeaderCell>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id}>
            {row(item).map((cell, index) => (
              <TableCell key={columns[index]}>{cell}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const loadHistory = (signal) => api.index.history({}, signal).then((data) => data.runs);
const loadJobs = (signal) => api.index.jobs(signal).then((data) => data.jobs);
const loadQueue = (signal) => api.index.requests(signal).then((data) => data.requests);

export function IndexingPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { refresh, bump } = useIndexing();
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`))?.value ?? 'activity';

  const cancel = async (id) => {
    await api.index.cancelRequest(id).catch(() => {});
    bump();
  };

  return (
    <div className={styles.page}>
      <PageHeader title="Indexing" lead="What is being read, what was, and what waits." />
      <div className={styles.bar}>
        <TabList
          className={styles.grow}
          selectedValue={current}
          onTabSelect={(_, data) => navigate(`/indexing/${data.value}`)}
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value}>
              {tab.label}
            </Tab>
          ))}
        </TabList>
        <ToolButton label="Refresh" icon={<ArrowSync20Regular />} onClick={refresh} />
      </div>
      {current === 'activity' && <Activity />}
      {current === 'history' && (
        <Listing
          label="History"
          load={loadHistory}
          empty="No runs yet."
          columns={['Run', 'Target', 'Status', 'Files', 'Failed', 'Credits', 'Started', 'Finished']}
          row={(run) => [
            run.id,
            run.target ? baseName(run.target) : 'All sources',
            <StatusBadge key="s" status={run.status} title={run.error ?? undefined} />,
            `${run.files_processed} of ${run.files_total}`,
            run.files_failed,
            formatCredits(run.credits_charged),
            formatDate(run.started_at),
            formatDate(run.completed_at),
          ]}
        />
      )}
      {current === 'jobs' && (
        <Listing
          label="Remote jobs"
          load={loadJobs}
          empty="No remote jobs. They appear when pages are sent to GitHub for OCR."
          columns={['Job', 'Tier', 'Status', 'Images', 'Size', 'Credits', 'Submitted', 'Completed']}
          row={(job) => [
            job.id,
            job.tier,
            <StatusBadge key="s" status={job.status} title={job.error ?? undefined} />,
            job.images,
            formatBytes(job.size_bytes),
            job.credits,
            formatDate(job.submitted_at),
            formatDate(job.completed_at),
          ]}
        />
      )}
      {current === 'queue' && (
        <Listing
          label="Queue"
          load={loadQueue}
          empty="The queue is empty. Requests wait here when the background service does the work."
          columns={['Request', 'Target', 'Mode', 'Status', 'Why', 'Requested', '']}
          row={(job) => [
            job.id,
            job.target ? baseName(String(job.target)) : 'All sources',
            job.mode,
            <StatusBadge key="s" status={job.status} title={job.error ?? undefined} />,
            job.status === 'waiting_credits'
              ? `Credits are back ${formatDate(job.resume_at)}`
              : (job.reason ?? ''),
            formatDate(job.requested_at),
            job.open ? (
              <Button
                key="c"
                size="small"
                icon={<Dismiss20Regular />}
                onClick={() => cancel(job.id)}
              >
                Cancel
              </Button>
            ) : null,
          ]}
        />
      )}
    </div>
  );
}
