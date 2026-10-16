import {
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowSync20Regular } from '@fluentui/react-icons';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { InstalledTab } from '../addons/InstalledTab.jsx';
import { BundlesTab } from '../addons/BundlesTab.jsx';
import { DiscoverTab } from '../addons/DiscoverTab.jsx';
import { useAddonsJob } from '../addons/useAddonsJob.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { ToolButton } from '../components/ToolButton.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
  log: {
    margin: 0,
    maxHeight: '180px',
    overflow: 'auto',
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    whiteSpace: 'pre-wrap',
  },
});

const TABS = [
  { value: 'installed', label: 'Installed' },
  { value: 'discover', label: 'Discover' },
  { value: 'get', label: 'Get more' },
];

export function AddonsPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const notify = useNotify();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [asking, setAsking] = useState(
    /** @type {{ kind: 'bundle' | 'update', item: any } | null} */ (null),
  );
  const [reload, setReload] = useState(0);
  const [catalog, setCatalog] = useState(null);
  const [checking, setChecking] = useState(false);
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`))?.value ?? 'installed';

  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const finished = useCallback(
    (job) => {
      refresh();
      if (!job.error)
        notify({
          title: job.action === 'update' ? 'Add-on updated' : 'Bundle installed',
          body: 'Restart VethuQ to start using it.',
        });
      else notify({ title: 'Could not finish', body: job.error, intent: 'error' });
    },
    [notify, refresh],
  );
  const { job, run } = useAddonsJob(finished);

  useEffect(() => {
    const controller = new AbortController();
    api.addons.list(controller.signal).then(
      (result) => {
        setData(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (current !== 'discover') return undefined;
    const controller = new AbortController();
    api.addons.catalog(controller.signal).then(
      (result) => setCatalog(result),
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [current, reload]);

  const checkNow = async () => {
    setChecking(true);
    try {
      const result = await api.addons.catalogRefresh(true);
      setCatalog(result);
      const { status, detail } = result.catalog;
      if (status === 'skipped' || status === 'offline' || status === 'rejected')
        notify({ title: 'Could not get a newer list', body: detail || status, intent: 'warning' });
    } catch (failure) {
      notify({ title: 'Could not check', body: failure.message, intent: 'error' });
    } finally {
      setChecking(false);
    }
  };

  const toggle = async (addon, on) => {
    try {
      await api.addons.setEnabled(addon.id, on);
      notify({ title: `${addon.id} will be ${on ? 'on' : 'off'} after a restart` });
    } catch (failure) {
      notify({ title: 'Could not change it', body: failure.message, intent: 'error' });
    }
    refresh();
  };

  const confirm = async () => {
    const { kind, item } = asking;
    setAsking(null);
    try {
      await run(() =>
        kind === 'bundle' ? api.addons.install(item.id) : api.addons.update(item.id),
      );
    } catch (failure) {
      notify({ title: 'Could not start', body: failure.message, intent: 'error' });
    }
  };

  const restart = data?.installed.some((a) => a.restart);

  return (
    <div className={styles.page}>
      <PageHeader
        title="Add-ons"
        lead="What extends VethuQ: file types, languages, search engines and OCR."
      />
      <div className={styles.bar}>
        <TabList
          className={styles.grow}
          selectedValue={current}
          onTabSelect={(_, d) => navigate(`/addons/${d.value}`)}
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value}>
              {tab.label}
            </Tab>
          ))}
        </TabList>
        <ToolButton label="Refresh" icon={<ArrowSync20Regular />} onClick={refresh} />
      </div>
      {restart && (
        <MessageBar intent="info">
          <MessageBarBody>Restart VethuQ for the changes to take effect.</MessageBarBody>
        </MessageBar>
      )}
      {job.running && (
        <MessageBar intent="info">
          <MessageBarBody>
            <Spinner size="extra-tiny" /> {job.action === 'update' ? 'Updating' : 'Installing'}{' '}
            {job.target}…
          </MessageBarBody>
        </MessageBar>
      )}
      {job.error && (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{job.error}</MessageBarTitle>
            <pre className={styles.log}>{job.log.join('\n')}</pre>
          </MessageBarBody>
        </MessageBar>
      )}
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error.message}</MessageBarBody>
        </MessageBar>
      )}
      {!data && !error && <Spinner size="small" label="Loading add-ons" />}
      {data && current === 'installed' && (
        <InstalledTab
          addons={data.installed}
          busy={job.running}
          onToggle={toggle}
          onUpdate={(item) => setAsking({ kind: 'update', item })}
        />
      )}
      {current === 'discover' && catalog && (
        <DiscoverTab data={catalog} busy={checking} onRefresh={checkNow} />
      )}
      {data && current === 'get' && (
        <BundlesTab
          bundles={data.bundles}
          install={data.install}
          busy={job.running}
          onInstall={(item) => setAsking({ kind: 'bundle', item })}
        />
      )}
      <ConfirmDialog
        open={asking !== null}
        title={
          asking?.kind === 'bundle' ? `Install ${asking.item.id}?` : `Update ${asking?.item.id}?`
        }
        confirmLabel={asking?.kind === 'bundle' ? 'Install' : 'Update'}
        onConfirm={confirm}
        onCancel={() => setAsking(null)}
      >
        It downloads packages from the internet with pip, which can take a minute. You restart
        VethuQ afterwards to start using them.
      </ConfirmDialog>
    </div>
  );
}
