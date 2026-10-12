import {
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
import { api } from '../api/client.js';
import { useApi } from '../api/useApi.js';
import { CatalogTabs } from '../components/CatalogTabs.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { strings } from '../strings.js';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL },
  section: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  table: { maxWidth: '520px' },
  label: { color: tokens.colorNeutralForeground2 },
});

export function AboutPage() {
  const styles = useStyles();
  const about = useApi(api.about);
  const catalog = useApi(api.catalog);

  return (
    <div className={styles.page}>
      <PageHeader title={strings.about.title} lead={strings.about.lead} />
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
