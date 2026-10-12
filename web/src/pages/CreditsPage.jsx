import { Tab, TabList, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowSync20Regular, TicketDiagonal20Regular } from '@fluentui/react-icons';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { useCredits } from '../credits/CreditsProvider.jsx';
import { DailyTab } from '../credits/DailyTab.jsx';
import { GrantsTab } from '../credits/GrantsTab.jsx';
import { LedgerTab } from '../credits/LedgerTab.jsx';
import { OverviewTab } from '../credits/OverviewTab.jsx';
import { RedeemDialog } from '../credits/RedeemDialog.jsx';
import { UsageTab } from '../credits/UsageTab.jsx';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
});

const TABS = [
  { value: 'overview', label: 'Overview', element: <OverviewTab /> },
  { value: 'grants', label: 'Credits held', element: <GrantsTab /> },
  { value: 'daily', label: 'Usage by day', element: <DailyTab /> },
  { value: 'usage', label: 'Usage by source', element: <UsageTab /> },
  { value: 'ledger', label: 'Ledger', element: <LedgerTab /> },
];

export function CreditsPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const notify = useNotify();
  const { bump } = useIndexing();
  const { refresh } = useCredits();
  const [redeeming, setRedeeming] = useState(false);
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`)) ?? TABS[0];

  const reload = () => {
    refresh();
    bump();
  };

  return (
    <div className={styles.page}>
      <PageHeader
        title="Credits"
        lead="What reading pages costs, what you have, and where it went."
      />
      <div className={styles.bar}>
        <TabList
          className={styles.grow}
          selectedValue={current.value}
          onTabSelect={(_, d) => navigate(`/credits/${d.value}`)}
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value}>
              {tab.label}
            </Tab>
          ))}
        </TabList>
        <ToolButton
          label="Redeem a licence"
          icon={<TicketDiagonal20Regular />}
          onClick={() => setRedeeming(true)}
        />
        <ToolButton label="Refresh" icon={<ArrowSync20Regular />} onClick={reload} />
      </div>
      {current.element}
      <RedeemDialog
        open={redeeming}
        onClose={() => setRedeeming(false)}
        onRedeemed={(done) => {
          reload();
          if (done.some((r) => r.added)) notify({ title: 'Licence redeemed' });
        }}
      />
    </div>
  );
}
