import {
  Badge,
  Button,
  Checkbox,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowClockwise20Regular,
  ArrowDownload20Regular,
  ArrowSync20Regular,
  Broom20Regular,
  Delete20Regular,
  FolderOpen20Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { DataTable } from '../components/DataTable.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { GroupHeading } from '../components/GroupHeading.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { formatBytes } from '../format.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { useOcrJob } from './useOcrJob.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  grow: { flexGrow: 1 },
  muted: { color: tokens.colorNeutralForeground3 },
});

function Ready({ ok, reason }) {
  return (
    <Badge appearance="tint" color={ok ? 'success' : 'warning'} title={ok ? undefined : reason}>
      {ok ? 'Ready' : 'Unavailable'}
    </Badge>
  );
}

const ENGINE_COLUMNS = [
  { key: 'label', label: 'Engine' },
  { key: 'profiles', label: 'Model sets', render: (e) => e.profiles.join(', ') || '—' },
  {
    key: 'available',
    label: 'Status',
    render: (e) => (
      <span>
        <Ready ok={e.available} reason={e.reason} />
        {!e.available && e.reason && <Text> {e.reason}</Text>}
      </span>
    ),
  },
];

const PHASE_COLUMNS = [
  { key: 'order', label: 'Order' },
  { key: 'label', label: 'Phase' },
  { key: 'profile', label: 'Model set' },
  { key: 'angles', label: 'Rotations', render: (p) => p.angles.map((a) => `${a}°`).join(', ') },
  {
    key: 'available',
    label: 'Status',
    render: (p) => (
      <span>
        <Ready ok={p.available} reason={p.reason} />
        {!p.available && p.reason && <Text> {p.reason}</Text>}
      </span>
    ),
  },
];

/** The OCR tab of Settings: engines and phases that are installed, and the model files. */
export function OcrPanel() {
  const styles = useStyles();
  const notify = useNotify();
  const platform = usePlatform();
  const [overview, setOverview] = useState(null);
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);
  const [language, setLanguage] = useState('');
  const [asking, setAsking] = useState(
    /** @type {'redownload' | 'remove' | 'clean' | null} */ (null),
  );
  const [shared, setShared] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  const load = useCallback(() => setReload((n) => n + 1), []);

  const finished = useCallback(
    (job) => {
      load();
      if (job.error)
        notify({ title: 'Could not download the models', body: job.error, intent: 'error' });
      else notify({ title: 'Models are ready' });
    },
    [load, notify],
  );
  const { job, start } = useOcrJob(finished);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.ocr.overview(controller.signal), api.ocr.models(controller.signal)]).then(
      ([info, list]) => {
        setOverview(info);
        setModels(list);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [reload]);

  const languages = useMemo(() => {
    const found = new Set();
    (models?.items ?? []).forEach((m) => m.languages.forEach((l) => found.add(l)));
    return [...found].sort();
  }, [models]);
  const options = [
    { value: '', label: 'All languages' },
    ...languages.map((l) => ({ value: l, label: l })),
  ];
  const shown = useMemo(
    () => (models?.items ?? []).filter((m) => !language || m.languages.includes(language)),
    [models, language],
  );
  const picked = language ? [language] : undefined;

  const run = async (action, body) => {
    try {
      await start(action, body);
    } catch (failure) {
      notify({ title: 'Could not start', body: failure.message, intent: 'error' });
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      if (asking === 'redownload') {
        await run('redownload', { languages: picked, names: shown.map((m) => m.name) });
      } else if (asking === 'remove') {
        const { removed } = await api.ocr.clear([language], shared);
        notify({ title: `Removed ${removed.length} model${removed.length === 1 ? '' : 's'}` });
        load();
      } else if (asking === 'clean') {
        const { removed } = await api.ocr.clean();
        notify({
          title: `Removed ${removed.length} unused file${removed.length === 1 ? '' : 's'}`,
        });
        load();
      }
    } catch (failure) {
      notify({ title: 'Could not do that', body: failure.message, intent: 'error' });
    } finally {
      setBusy(false);
      setAsking(null);
      setShared(false);
    }
  };

  if (error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!overview || !models) return <Spinner size="small" label="Loading OCR" />;

  const state = (m) => {
    const progress = job.progress[m.name];
    if (job.running && (progress === 'downloading' || (!m.installed && !progress)))
      return (
        <Badge appearance="tint" color="brand">
          Downloading
        </Badge>
      );
    if (m.installed)
      return (
        <Badge appearance="tint" color="success">
          Installed
        </Badge>
      );
    if (progress === 'failed')
      return (
        <Badge appearance="tint" color="danger">
          Failed
        </Badge>
      );
    return (
      <Badge appearance="tint" color="informative">
        Not downloaded
      </Badge>
    );
  };

  const missing = shown.filter((m) => !m.installed).length;
  const modelColumns = [
    { key: 'name', label: 'Model' },
    { key: 'engine', label: 'Engine' },
    { key: 'kind', label: 'Kind', render: (m) => m.kind.replace(/_/g, ' ') },
    {
      key: 'languages',
      label: 'Used for',
      render: (m) => (m.shared ? 'All languages' : m.languages.join(', ')),
    },
    { key: 'status', label: 'Status', render: state },
    {
      key: 'size_bytes',
      label: 'Size',
      align: 'end',
      render: (m) => (m.installed ? formatBytes(m.size_bytes) : '—'),
    },
  ];

  const titles = {
    redownload: 'Download the models again?',
    remove: `Remove the models for ${language}?`,
    clean: 'Remove models nothing uses?',
  };
  const bodies = {
    redownload:
      'The models shown are deleted and downloaded again. Reading pages needs them, so keep the connection on until it is done.',
    remove:
      'Models only this language uses are deleted. They download again when a page needs them.',
    clean: 'Model files that no installed language needs any more are deleted.',
  };

  return (
    <div className={styles.root}>
      <GroupHeading
        title="Engines"
        note="What reads the text of scanned pages. OCR depth and GPU use are in Indexing."
      />
      <DataTable
        label="OCR engines"
        columns={ENGINE_COLUMNS}
        rows={overview.engines}
        rowKey={(e) => e.id}
      />
      <GroupHeading
        title="Phases"
        note="Pages are read quickly first. Deeper phases try again on pages that need it."
      />
      <DataTable
        label="OCR phases"
        columns={PHASE_COLUMNS}
        rows={overview.phases}
        rowKey={(p) => p.id}
      />
      <GroupHeading
        title="Models"
        note="Model files are downloaded when a page needs them. You can fetch them ahead of time."
      />
      <div className={styles.bar}>
        <FilterSelect label="Language" value={language} options={options} onChange={setLanguage} />
        <ToolButton
          label="Download missing models"
          icon={<ArrowDownload20Regular />}
          disabled={job.running || missing === 0}
          onClick={() => run('download', { languages: picked })}
        />
        <ToolButton
          label="Download again"
          icon={<ArrowClockwise20Regular />}
          disabled={job.running || shown.length === 0}
          onClick={() => setAsking('redownload')}
        />
        <ToolButton
          label={
            language ? `Remove models for ${language}` : 'Pick a language to remove its models'
          }
          icon={<Delete20Regular />}
          disabled={job.running || !language}
          onClick={() => setAsking('remove')}
        />
        <ToolButton
          label="Remove models nothing uses"
          icon={<Broom20Regular />}
          disabled={job.running}
          onClick={() => setAsking('clean')}
        />
        <span className={styles.grow} />
        <ToolButton label="Refresh" icon={<ArrowSync20Regular />} onClick={load} />
      </div>
      <Text className={styles.muted}>
        {models.installed} of {models.items.length} models installed (
        {formatBytes(models.size_bytes)}) in {models.folder}
        {platform.reveal && (
          <Button
            size="small"
            appearance="subtle"
            aria-label="Show the models folder"
            icon={<FolderOpen20Regular />}
            onClick={() => api.os.reveal(models.folder).catch(() => {})}
          />
        )}
      </Text>
      {job.running && (
        <MessageBar intent="info">
          <MessageBarBody>
            <Spinner size="extra-tiny" />{' '}
            {job.action === 'redownload' ? 'Downloading again' : 'Downloading'} models…
          </MessageBarBody>
        </MessageBar>
      )}
      <DataTable label="OCR models" columns={modelColumns} rows={shown} rowKey={(m) => m.name} />
      {shown.length === 0 && <Text className={styles.muted}>No models for this language.</Text>}
      <ConfirmDialog
        open={asking !== null}
        title={asking ? titles[asking] : ''}
        confirmLabel={
          asking === 'redownload' ? 'Download again' : asking === 'remove' ? 'Remove' : 'Clean up'
        }
        busy={busy}
        onConfirm={confirm}
        onCancel={() => setAsking(null)}
      >
        {asking && bodies[asking]}
        {asking === 'remove' && (
          <Checkbox
            label="Also remove models shared by every language"
            checked={shared}
            onChange={(_, d) => setShared(d.checked === true)}
          />
        )}
      </ConfirmDialog>
    </div>
  );
}
