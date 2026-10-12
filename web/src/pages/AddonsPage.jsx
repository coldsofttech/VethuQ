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
import { PacksTab } from '../addons/PacksTab.jsx';
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
    /** @type {{ kind: 'pack' | 'update', item: any } | null} */ (null),
  );
  const [reload, setReload] = useState(0);
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`))?.value ?? 'installed';

  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const finished = useCallback(
    (job) => {
      refresh();
      if (!job.error)
        notify({
          title: job.action === 'update' ? 'Add-on updated' : 'Pack installed',
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
      await run(() => (kind === 'pack' ? api.addons.install(item.id) : api.addons.update(item.id)));
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
      {data && current === 'get' && (
        <PacksTab
          packs={data.packs}
          install={data.install}
          busy={job.running}
          onInstall={(item) => setAsking({ kind: 'pack', item })}
        />
      )}
      <ConfirmDialog
        open={asking !== null}
        title={
          asking?.kind === 'pack' ? `Install ${asking.item.id}?` : `Update ${asking?.item.id}?`
        }
        confirmLabel={asking?.kind === 'pack' ? 'Install' : 'Update'}
        onConfirm={confirm}
        onCancel={() => setAsking(null)}
      >
        It downloads packages from the internet with pip, which can take a minute. You restart
        VethuQ afterwards to start using them.
      </ConfirmDialog>
    </div>
  );
}
