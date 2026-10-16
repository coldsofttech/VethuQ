import {
  Badge,
  Button,
  Card,
  CardHeader,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  Switch,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useMemo, useState } from 'react';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: tokens.spacingHorizontalM,
  },
  badges: { display: 'flex', gap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
  muted: { color: tokens.colorNeutralForeground3 },
  actions: { display: 'flex', gap: tokens.spacingHorizontalM, alignItems: 'center' },
  more: { whiteSpace: 'pre-wrap', margin: 0 },
});

const STATE_WORDS = {
  enabled: ['Installed', 'success'],
  disabled: ['Installed, turned off', 'warning'],
  incompatible: ['Installed, needs another VethuQ', 'danger'],
  failed: ['Installed, could not start', 'danger'],
  not_installed: ['Not installed', 'informative'],
};

const LICENCE_WORDS = { free: 'Free', licensed: 'Licensed' };
const STATUS_WORDS = { coming_soon: 'Coming soon', deprecated: 'No longer offered' };

/** Where to go to ask for something, or the plain instruction when the catalog gives no address. */
function Ask({ item, styles }) {
  if (item.installed || item.status === 'deprecated') return null;
  return item.request_url ? (
    <Link href={item.request_url} target="_blank" rel="noreferrer">
      Ask for it
    </Link>
  ) : (
    <Text className={styles.muted}>Ask your administrator for it.</Text>
  );
}

function AddonCard({ item, styles }) {
  const [state, tone] = STATE_WORDS[item.state] ?? [item.state, 'informative'];
  return (
    <Card aria-label={item.label}>
      <CardHeader
        header={<Text weight="semibold">{item.label}</Text>}
        description={<Text className={styles.muted}>{item.summary}</Text>}
      />
      <div className={styles.badges}>
        <Badge appearance="tint" color={tone}>
          {state}
        </Badge>
        {LICENCE_WORDS[item.licence] && (
          <Badge appearance="outline">{LICENCE_WORDS[item.licence]}</Badge>
        )}
        {STATUS_WORDS[item.status] && (
          <Badge appearance="tint" color="warning">
            {STATUS_WORDS[item.status]}
          </Badge>
        )}
        {item.kind && <Badge appearance="outline">{item.kind}</Badge>}
        {item.bundles.map((bundle) => (
          <Badge key={bundle} appearance="outline">
            Bundle: {bundle}
          </Badge>
        ))}
      </div>
      {item.description && (
        <details>
          <summary>More about it</summary>
          <p className={styles.more}>{item.description}</p>
        </details>
      )}
      {item.requires_newer_client && (
        <Text className={styles.muted}>Needs VethuQ {item.min_client} or newer.</Text>
      )}
      <div className={styles.actions}>
        {item.docs_url && (
          <Link href={item.docs_url} target="_blank" rel="noreferrer">
            Learn more
          </Link>
        )}
        <Ask item={item} styles={styles} />
      </div>
    </Card>
  );
}

function BundleCard({ item, styles }) {
  return (
    <Card aria-label={`${item.label} bundle`}>
      <CardHeader
        header={<Text weight="semibold">{item.label} bundle</Text>}
        description={<Text className={styles.muted}>{item.summary}</Text>}
      />
      <div className={styles.badges}>
        <Badge appearance="tint" color={item.complete ? 'success' : 'informative'}>
          {item.installed.length} of {item.addons.length} installed
        </Badge>
        {STATUS_WORDS[item.status] && (
          <Badge appearance="tint" color="warning">
            {STATUS_WORDS[item.status]}
          </Badge>
        )}
      </div>
      <Text className={styles.muted}>Includes: {item.addons.join(', ')}</Text>
      {item.description && (
        <details>
          <summary>More about it</summary>
          <p className={styles.more}>{item.description}</p>
        </details>
      )}
      <div className={styles.actions}>
        {item.docs_url && (
          <Link href={item.docs_url} target="_blank" rel="noreferrer">
            Learn more
          </Link>
        )}
        {!item.complete && item.status !== 'deprecated' && (
          <Ask item={{ ...item, installed: false }} styles={styles} />
        )}
      </div>
    </Card>
  );
}

/**
 * Every add-on and bundle that exists, installed here or not, with a description and where to ask
 * for the ones that are not. It reads what VethuQ has saved; "Check now" looks for a newer list.
 * @param {{ data: { catalog: any, addons: any[], bundles: any[] }, busy: boolean, onRefresh: () => void }} props
 */
export function DiscoverTab({ data, busy, onRefresh }) {
  const styles = useStyles();
  const [text, setText] = useState('');
  const [missing, setMissing] = useState(false);
  const needle = text.trim().toLowerCase();
  const matches = (item) =>
    (!needle ||
      `${item.id} ${item.label} ${item.summary} ${item.kind}`.toLowerCase().includes(needle)) &&
    (!missing || !item.installed);
  const addons = useMemo(() => data.addons.filter(matches), [data, needle, missing]); // eslint-disable-line react-hooks/exhaustive-deps
  const bundles = useMemo(
    () => data.bundles.filter((b) => matches({ ...b, installed: b.complete })),
    [data, needle, missing], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const received = data.catalog.source !== 'baseline';
  return (
    <div className={styles.root}>
      {!received && (
        <MessageBar intent="info">
          <MessageBarBody>
            No list of available add-ons has been received yet, so only what is installed here is
            shown. {data.catalog.detail}
          </MessageBarBody>
        </MessageBar>
      )}
      {data.catalog.update_required && (
        <MessageBar intent="warning">
          <MessageBarBody>A newer VethuQ is needed to read the newest list.</MessageBarBody>
        </MessageBar>
      )}
      <div className={styles.bar}>
        <Input
          aria-label="Search add-ons"
          placeholder="Search add-ons"
          value={text}
          onChange={(_, d) => setText(d.value)}
        />
        <Switch
          label="Only those not installed"
          checked={missing}
          onChange={(_, d) => setMissing(d.checked)}
        />
        <Button disabled={busy} onClick={onRefresh}>
          Check now
        </Button>
      </div>
      <Text weight="semibold" as="h3">
        Add-ons
      </Text>
      {addons.length ? (
        <div className={styles.grid}>
          {addons.map((item) => (
            <AddonCard key={item.id} item={item} styles={styles} />
          ))}
        </div>
      ) : (
        <Text className={styles.muted}>No add-ons match.</Text>
      )}
      {data.bundles.length > 0 && (
        <>
          <Text weight="semibold" as="h3">
            Bundles
          </Text>
          <div className={styles.grid}>
            {bundles.map((item) => (
              <BundleCard key={item.id} item={item} styles={styles} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
