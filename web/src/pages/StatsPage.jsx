import { Tab, TabList, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowSync20Regular } from '@fluentui/react-icons';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { BreakdownTab } from '../stats/BreakdownTab.jsx';
import { FilterBar } from '../stats/FilterBar.jsx';
import { NO_FILTERS } from '../stats/filters.js';
import { SummaryTab } from '../stats/SummaryTab.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
});

const TABS = [
  { value: 'summary', label: 'Summary' },
  { value: 'breakdown', label: 'Breakdown' },
];

export function StatsPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [filters, setFilters] = useState(NO_FILTERS);
  const [refresh, setRefresh] = useState(0);
  const current = TABS.find((tab) => pathname.endsWith(`/${tab.value}`))?.value ?? 'summary';

  return (
    <div className={styles.page}>
      <PageHeader title="Statistics" lead="What has been read, and how well." />
      <div className={styles.bar}>
        <TabList
          className={styles.grow}
          selectedValue={current}
          onTabSelect={(_, data) => navigate(`/stats/${data.value}`)}
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value}>
              {tab.label}
            </Tab>
          ))}
        </TabList>
        <ToolButton
          label="Refresh"
          icon={<ArrowSync20Regular />}
          onClick={() => setRefresh((n) => n + 1)}
        />
      </div>
      <FilterBar filters={filters} onChange={setFilters} />
      {current === 'summary' ? (
        <SummaryTab filters={filters} refresh={refresh} />
      ) : (
        <BreakdownTab
          filters={filters}
          refresh={refresh}
          onNarrow={(key, value) => setFilters((f) => ({ ...f, [key]: value }))}
        />
      )}
    </div>
  );
}
