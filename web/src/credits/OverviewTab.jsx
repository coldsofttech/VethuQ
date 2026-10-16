import {
  MessageBar,
  MessageBarBody,
  ProgressBar,
  Spinner,
  Tab,
  TabList,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { formatCredits, formatDate } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { walletLabel } from './labels.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
  cards: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
    gap: tokens.spacingHorizontalM,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingVerticalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
  },
  wide: { gridColumn: '1 / -1' },
  muted: { color: tokens.colorNeutralForeground3 },
});

function Card({ title, value, note, children, wide }) {
  const styles = useStyles();
  return (
    <div className={`${styles.card} ${wide ? styles.wide : ''}`}>
      <Text className={styles.muted}>{title}</Text>
      <Text size={700} weight="semibold">
        {value}
      </Text>
      {note && <Text className={styles.muted}>{note}</Text>}
      {children}
    </div>
  );
}

export function OverviewTab() {
  const styles = useStyles();
  const { version } = useIndexing();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [wallet, setWallet] = useState('local');

  useEffect(() => {
    const controller = new AbortController();
    api.credits.wallets(controller.signal).then(
      (result) => {
        setData(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [version]);

  if (error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!data) return <Spinner size="small" label="Loading credits" />;

  const current = data.wallets.find((w) => w.wallet === wallet) ?? data.wallets[0];
  const totals = data.totals.find((t) => t.wallet === current.wallet);
  const share = current.daily_allowance > 0 ? current.daily_used / current.daily_allowance : 0;
  const bonus = current.bonus_active
    ? `, including ${formatCredits(current.bonus)} for sharing metrics`
    : '';

  return (
    <div className={styles.root}>
      {data.wallets.length > 1 && (
        <TabList
          size="small"
          selectedValue={current.wallet}
          onTabSelect={(_, d) => setWallet(String(d.value))}
        >
          {data.wallets.map((w) => (
            <Tab key={w.wallet} value={w.wallet}>
              {walletLabel(w.wallet)}
            </Tab>
          ))}
        </TabList>
      )}
      <div className={styles.cards}>
        <Card
          wide
          title="Today's allowance"
          value={`${formatCredits(current.daily)} left of ${formatCredits(current.daily_allowance)}`}
          note={`${formatCredits(current.daily_used)} used today${bonus}. Resets ${formatDate(current.next_reset)}.${current.limit_note ? ` Limit: ${current.limit_note}.` : ''}`}
        >
          <ProgressBar
            value={share}
            color={share >= 1 ? 'error' : share > 0.8 ? 'warning' : 'brand'}
          />
        </Card>
        <Card
          title="Promotion today"
          value={formatCredits(current.promotional)}
          note="Spent first"
        />
        <Card
          title="One-off"
          value={formatCredits(current.one_off)}
          note="Starter and licence credits"
        />
        <Card
          title="Available now"
          value={formatCredits(current.total)}
          note="Everything that can be spent"
        />
      </div>
      <Text weight="semibold">Since the beginning</Text>
      <div className={styles.cards}>
        <Card title="Received" value={formatCredits(totals.received)} />
        <Card title="Consumed" value={formatCredits(totals.consumed)} />
        <Card title="Lapsed unused" value={formatCredits(totals.lapsed)} />
        <Card title="Remaining" value={formatCredits(totals.remaining)} />
      </div>
    </div>
  );
}
