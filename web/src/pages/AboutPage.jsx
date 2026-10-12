import {
  Button,
  MessageBar,
  MessageBarBody,
  Spinner,
  Subtitle2,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Copy20Regular, Checkmark20Regular } from '@fluentui/react-icons';
import { useState } from 'react';
import { api } from '../api/client.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { useApi } from '../api/useApi.js';
import { CatalogTabs } from '../components/CatalogTabs.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { strings } from '../strings.js';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL },
  section: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  table: { maxWidth: '520px' },
  label: { color: tokens.colorNeutralForeground2 },
  top: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: tokens.spacingHorizontalL,
    flexWrap: 'wrap',
  },
  copy: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: tokens.spacingVerticalXS,
    maxWidth: '360px',
  },
  hint: { color: tokens.colorNeutralForeground3, textAlign: 'right' },
});

/** Copy text to the clipboard: the modern API, then the old way for hosts that refuse it. */
export async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    return;
  } catch {
    // fall through
  }
  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand('copy');
  area.remove();
  if (!ok) throw new Error('copy refused');
}

/** What a support request needs: the service's report, plus what only this window knows. */
export function withInterface(report, platform) {
  const host = platform.kind === 'desktop' ? 'Desktop application' : 'Web';
  return `${report}\n### Interface\n- Host: ${host}\n- Browser engine: ${navigator.userAgent}\n`;
}

export function AboutPage() {
  const styles = useStyles();
  const platform = usePlatform();
  const [copy, setCopy] = useState(/** @type {'idle' | 'copied' | 'failed'} */ ('idle'));
  const about = useApi(api.about);
  const catalog = useApi(api.catalog);

  const copySupportInfo = async () => {
    try {
      await copyText(withInterface(await api.supportInfo(), platform));
      setCopy('copied');
      window.setTimeout(() => setCopy('idle'), 3000);
    } catch {
      setCopy('failed');
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.top}>
        <PageHeader title={strings.about.title} lead={strings.about.lead} />
        <div className={styles.copy}>
          <Button
            appearance="primary"
            icon={copy === 'copied' ? <Checkmark20Regular /> : <Copy20Regular />}
            onClick={copySupportInfo}
          >
            {copy === 'copied' ? strings.about.copied : strings.about.copy}
          </Button>
          <Text size={200} className={styles.hint}>
            {strings.about.copyHint}
          </Text>
          {copy === 'failed' && (
            <MessageBar intent="error">
              <MessageBarBody>{strings.about.copyFailed}</MessageBarBody>
            </MessageBar>
          )}
        </div>
      </div>
      {(about.error || catalog.error) && (
        <MessageBar intent="error">
          <MessageBarBody>{strings.errors.loadFailed}</MessageBarBody>
        </MessageBar>
      )}
      {about.loading && <Spinner size="small" />}
      {about.data && (
        <Table className={styles.table} aria-label={strings.about.title}>
          <TableBody>
            {Object.entries(strings.about.rows).map(([key, label]) => (
              <TableRow key={key}>
                <TableCell>
                  <Text className={styles.label}>{label}</Text>
                </TableCell>
                <TableCell>
                  <Text weight="semibold">{String(about.data[key])}</Text>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <section className={styles.section}>
        <Subtitle2 as="h2">{strings.about.installed}</Subtitle2>
        {catalog.loading && <Spinner size="small" />}
        {catalog.data && <CatalogTabs catalog={catalog.data} />}
      </section>
    </div>
  );
}
