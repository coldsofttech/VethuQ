import {
  Badge,
  Button,
  Link,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { GroupHeading } from '../components/GroupHeading.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { SettingFrame } from '../components/SettingFrame.jsx';
import { formatDate } from '../format.js';
import { useTask } from './useTask.js';

const usePanelStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  row: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  muted: { color: tokens.colorNeutralForeground3 },
  facts: {
    display: 'grid',
    gridTemplateColumns: 'max-content 1fr',
    gap: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalXL}`,
  },
});

/** Loads one thing from the service; `reload()` asks again. */
function useLoaded(load) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [count, setCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => setState({ data, error: null, loading: false }),
      (error) => error?.name !== 'AbortError' && setState({ data: null, error, loading: false }),
    );
    return () => controller.abort();
  }, [load, count]);
  return { ...state, reload: useCallback(() => setCount((n) => n + 1), []) };
}

function Failed({ error }) {
  return (
    <MessageBar intent="error">
      <MessageBarBody>{error.message}</MessageBarBody>
    </MessageBar>
  );
}

function Facts({ rows }) {
  const styles = usePanelStyles();
  return (
    <div className={styles.facts}>
      {rows
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([label, value]) => (
          <span key={label} style={{ display: 'contents' }}>
            <Text className={styles.muted}>{label}</Text>
            <Text>{value}</Text>
          </span>
        ))}
    </div>
  );
}

const loadDb = (signal) => api.maintenance.db(signal);
const loadUpdates = (signal) => api.maintenance.updates(signal);
const loadPolicy = (signal) => api.maintenance.policy(signal);
const loadIndex = (signal) => api.maintenance.searchIndex(signal);
const loadTiers = (signal) => api.maintenance.tiers(signal);

// ----- the database -------------------------------------------------------------------------

export function DatabasePanel() {
  const styles = usePanelStyles();
  const notify = useNotify();
  const db = useLoaded(loadDb);
  const finished = useCallback(
    (state) => {
      db.reload();
      if (state.error)
        notify({ title: 'The check could not run', body: state.error, intent: 'error' });
      else if (state.result?.ok) notify({ title: 'The database is healthy' });
      else
        notify({
          title: 'The database has problems',
          body: 'See the details in Settings.',
          intent: 'error',
        });
    },
    [db, notify],
  );
  const { task, start } = useTask('db-check', finished);

  const run = async (quick) => {
    try {
      await start(() => api.maintenance.dbCheck(quick));
    } catch (failure) {
      notify({ title: 'Could not start the check', body: failure.message, intent: 'error' });
    }
  };

  const last = db.data?.last;
  return (
    <div className={styles.root}>
      <GroupHeading
        title="Database check"
        note="Looks for damage in the database file. A full check reads the whole file."
      />
      <SettingFrame
        label="Check now"
        description="Quick skips checking that the indexes match their tables."
        testId="db-check"
      >
        <div className={styles.row}>
          <Button disabled={task.running} onClick={() => run(true)}>
            Quick check
          </Button>
          <Button disabled={task.running} onClick={() => run(false)}>
            Full check
          </Button>
          {task.running && <Spinner size="tiny" label="Checking" />}
        </div>
      </SettingFrame>
      {db.error && <Failed error={db.error} />}
      {last ? (
        <MessageBar intent={last.ok ? 'success' : 'error'}>
          <MessageBarBody>
            {last.ok
              ? 'No problems found'
              : `${last.errors.length} problem${last.errors.length === 1 ? '' : 's'} found`}
            {' · '}
            {last.quick ? 'quick' : 'full'} check, {formatDate(last.checked_at)}
            {last.errors.map((message) => (
              <div key={message}>{message}</div>
            ))}
          </MessageBarBody>
        </MessageBar>
      ) : (
        !db.loading && <Text className={styles.muted}>The database has not been checked yet.</Text>
      )}
    </div>
  );
}

// ----- updates ------------------------------------------------------------------------------

const UPDATE_WORDS = {
  up_to_date: 'You have the latest version',
  available: 'An update is available',
  below_minimum: 'An update is required',
  disabled: 'Update checks are off',
  unknown: 'Not checked yet',
};

export function UpdatesPanel() {
  const styles = usePanelStyles();
  const notify = useNotify();
  const updates = useLoaded(loadUpdates);
  const [busy, setBusy] = useState(false);

  const check = async () => {
    setBusy(true);
    try {
      await api.maintenance.updatesCheck(true);
      updates.reload();
    } catch (failure) {
      notify({ title: 'Could not check for updates', body: failure.message, intent: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const u = updates.data;
  return (
    <div className={styles.root}>
      <GroupHeading title="Updates" note="What VethuQ last found out about newer versions." />
      {updates.error && <Failed error={updates.error} />}
      {u && (
        <>
          <Facts
            rows={[
              ['This version', u.current],
              ['Latest', u.latest],
              ['Oldest still supported', u.minimum_supported],
              ['Installed as', u.distribution],
              ['Status', UPDATE_WORDS[u.status] ?? u.status],
              ['Notes', u.message],
            ]}
          />
          {u.release_notes_url && (
            <Link href={u.release_notes_url} target="_blank" rel="noreferrer">
              Release notes
            </Link>
          )}
          {u.disabled_by_environment && (
            <Text className={styles.muted}>Update checks are turned off on this computer.</Text>
          )}
        </>
      )}
      <div className={styles.row}>
        <Button disabled={busy} onClick={check}>
          {busy ? <Spinner size="tiny" /> : 'Check now'}
        </Button>
      </div>
    </div>
  );
}

// ----- the processing tiers -----------------------------------------------------------------

export function TiersPanel() {
  const styles = usePanelStyles();
  const notify = useNotify();
  const tiers = useLoaded(loadTiers);

  const change = async (call, success) => {
    try {
      await call();
      notify({ title: success });
      tiers.reload();
    } catch (failure) {
      notify({ title: 'Could not change the tier', body: failure.message, intent: 'error' });
    }
  };

  const columns = [
    { key: 'label', label: 'Tier' },
    { key: 'wallet', label: 'Credits from' },
    {
      key: 'available',
      label: 'Status',
      render: (t) => (
        <span>
          <Badge
            appearance="tint"
            color={t.available ? 'success' : 'warning'}
            title={t.reason || undefined}
          >
            {t.available ? 'Ready' : 'Unavailable'}
          </Badge>
          {!t.available && t.reason && <Text> {t.reason}</Text>}
        </span>
      ),
    },
    {
      key: 'selected',
      label: 'Default',
      render: (t) =>
        t.selected ? (
          <Badge appearance="filled" color="brand">
            Default
          </Badge>
        ) : (
          <Button
            size="small"
            onClick={() =>
              change(() => api.maintenance.tiersUse(t.id), `${t.label} is the default`)
            }
          >
            Use
          </Button>
        ),
    },
  ];

  return (
    <div className={styles.root}>
      <GroupHeading
        title="Where pages are read"
        note="Pages that need OCR are read on the default tier."
      />
      {tiers.error && <Failed error={tiers.error} />}
      {tiers.data && (
        <DataTable
          label="Processing tiers"
          columns={columns}
          rows={tiers.data.tiers}
          rowKey={(t) => t.id}
        />
      )}
      <div className={styles.row}>
        <Button
          size="small"
          onClick={() => change(() => api.maintenance.tiersReset(), 'Back to the local tier')}
        >
          Back to local
        </Button>
      </div>
    </div>
  );
}

// ----- the search index ---------------------------------------------------------------------

export function SearchIndexPanel() {
  const styles = usePanelStyles();
  const notify = useNotify();
  const index = useLoaded(loadIndex);
  const finished = useCallback(
    (state) => {
      index.reload();
      if (state.error)
        notify({ title: 'Could not rebuild the search index', body: state.error, intent: 'error' });
      else
        notify({
          title: 'The search index is rebuilt',
          body: `${state.result.pages} pages in ${state.result.seconds} s`,
        });
    },
    [index, notify],
  );
  const { task, start } = useTask('search-rebuild', finished);

  const rebuild = async () => {
    try {
      await start(() => api.maintenance.searchRebuild());
    } catch (failure) {
      notify({ title: 'Could not start', body: failure.message, intent: 'error' });
    }
  };

  const s = index.data;
  return (
    <div className={styles.root}>
      <GroupHeading
        title="Search index"
        note="The index searches read first. It is rebuilt by itself when the search add-ons change."
      />
      {index.error && <Failed error={index.error} />}
      {s && (
        <Facts
          rows={[
            [
              'Pages in the index',
              `${s.pages_indexed.toLocaleString()} of ${s.pages_total.toLocaleString()}`,
            ],
            ['Up to date', s.current ? 'Yes' : 'No: it will be rebuilt at the next search'],
            ['Fast text matching', s.full_text ? 'On' : 'Off (searches scan the index)'],
          ]}
        />
      )}
      <div className={styles.row}>
        <Button disabled={task.running} onClick={rebuild}>
          Rebuild the index
        </Button>
        {task.running && <Spinner size="tiny" label="Rebuilding" />}
      </div>
    </div>
  );
}

// ----- the signed policy --------------------------------------------------------------------

export function PolicyPanel() {
  const styles = usePanelStyles();
  const notify = useNotify();
  const policy = useLoaded(loadPolicy);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true);
    try {
      await api.maintenance.policyRefresh(true);
      policy.reload();
    } catch (failure) {
      notify({ title: 'Could not refresh the policy', body: failure.message, intent: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const p = policy.data;
  const features = p ? Object.entries(p.features) : [];
  const addons = p ? Object.entries(p.addons) : [];
  // The built-in policy knows no versions (they read 0.0.0), so they are not listed.
  const versions = p ? Object.entries(p.versions).filter(([, v]) => v.latest !== '0.0.0') : [];
  return (
    <div className={styles.root}>
      <GroupHeading
        title="Signed policy"
        note="Versions, notices and switches VethuQ checks without a reinstall. It is signed, and cached for offline use."
      />
      {policy.error && <Failed error={policy.error} />}
      {p && (
        <>
          <Facts
            rows={[
              ['Source', p.source === 'baseline' ? 'Built in (no policy received yet)' : p.source],
              ['Status', p.status],
              ['Sequence', p.sequence],
              [
                'Issued',
                p.source !== 'baseline' && p.issued_at ? formatDate(p.issued_at) : undefined,
              ],
              ['Key', p.source !== 'baseline' ? p.kid : undefined],
              ['Note', p.detail],
              [
                'Revoked keys',
                p.revoked_key_ids?.length ? p.revoked_key_ids.join(', ') : undefined,
              ],
            ]}
          />
          {p.trust_message && (
            <MessageBar intent="warning">
              <MessageBarBody>{p.trust_message}</MessageBarBody>
            </MessageBar>
          )}
          {p.update_required && (
            <MessageBar intent="warning">
              <MessageBarBody>A newer VethuQ is needed to receive new policy.</MessageBarBody>
            </MessageBar>
          )}
          {p.notices.map((n) => (
            <MessageBar
              key={n.id}
              intent={
                n.severity === 'warning' ? 'warning' : n.severity === 'critical' ? 'error' : 'info'
              }
            >
              <MessageBarBody>
                {n.message}{' '}
                {n.link && (
                  <Link href={n.link} target="_blank" rel="noreferrer">
                    More
                  </Link>
                )}
              </MessageBarBody>
            </MessageBar>
          ))}
          {versions.length > 0 && (
            <DataTable
              label="Policy versions"
              columns={[
                { key: 'name', label: 'Distribution' },
                { key: 'latest', label: 'Latest' },
                { key: 'minimum_supported', label: 'Oldest supported' },
              ]}
              rows={versions.map(([name, v]) => ({ name, ...v }))}
              rowKey={(r) => r.name}
            />
          )}
          {features.length > 0 && (
            <DataTable
              label="Policy features"
              columns={[
                { key: 'name', label: 'Feature' },
                { key: 'enabled', label: 'State', render: (r) => (r.enabled ? 'On' : 'Off') },
                { key: 'min_client', label: 'Needs version', render: (r) => r.min_client ?? '—' },
                { key: 'message', label: 'Note', render: (r) => r.message ?? '' },
              ]}
              rows={features.map(([name, f]) => ({ name, ...f }))}
              rowKey={(r) => r.name}
            />
          )}
          {addons.length > 0 && (
            <DataTable
              label="Policy add-ons"
              columns={[
                { key: 'name', label: 'Add-on' },
                {
                  key: 'enabled',
                  label: 'State',
                  render: (r) => (r.enabled ? 'Allowed' : 'Switched off'),
                },
                { key: 'latest', label: 'Latest', render: (r) => r.latest ?? '—' },
                { key: 'message', label: 'Note', render: (r) => r.message ?? '' },
              ]}
              rows={addons.map(([name, a]) => ({ name, ...a }))}
              rowKey={(r) => r.name}
            />
          )}
        </>
      )}
      <div className={styles.row}>
        <Button disabled={busy} onClick={refresh}>
          {busy ? <Spinner size="tiny" /> : 'Fetch the latest policy'}
        </Button>
      </div>
    </div>
  );
}
