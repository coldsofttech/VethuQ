import {
  MessageBar,
  MessageBarBody,
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
import { JobsTab } from '../github/JobsTab.jsx';
import { RunnerTab } from '../github/RunnerTab.jsx';
import { TokenBar } from '../github/TokenBar.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
});

const TABS = [
  { value: 'runner', label: 'Runner' },
  { value: 'jobs', label: 'Jobs' },
];

export function GitHubPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { refresh: collect } = useIndexing();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [token, setToken] = useState('');
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`))?.value ?? 'runner';

  useEffect(() => {
    const controller = new AbortController();
    api.github.overview(controller.signal).then(
      (result) => {
        setData(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [reload]);

  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const tokenField = { value: token, set: setToken };

  return (
    <div className={styles.page}>
      <PageHeader title="GitHub" lead="Read pages that need OCR in your own GitHub account." />
      <div className={styles.bar}>
        <TabList
          className={styles.grow}
          selectedValue={current}
          onTabSelect={(_, d) => navigate(`/github/${d.value}`)}
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value}>
              {tab.label}
            </Tab>
          ))}
        </TabList>
        <ToolButton
          label="Refresh and collect finished jobs"
          icon={<ArrowSync20Regular />}
          onClick={() => {
            collect();
            refresh();
          }}
        />
      </div>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error.message}</MessageBarBody>
        </MessageBar>
      )}
      {!data && !error && <Spinner size="small" label="Loading" />}
      {data && !data.enabled && (
        <MessageBar intent="warning">
          <MessageBarBody>{data.reason}</MessageBarBody>
        </MessageBar>
      )}
      {data?.enabled && current === 'runner' && (
        <>
          <TokenBar
            token={tokenField}
            state={data.token}
            onState={(state) => setData({ ...data, token: state })}
          />
          <RunnerTab data={data} token={tokenField} onChanged={refresh} />
        </>
      )}
      {data?.enabled && current === 'jobs' && <JobsTab />}
    </div>
  );
}
