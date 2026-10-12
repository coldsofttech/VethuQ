import {
  MessageBar,
  MessageBarBody,
  Spinner,
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
import { PageHeader } from '../components/PageHeader.jsx';
import { strings } from '../strings.js';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL },
  table: { maxWidth: '520px' },
  label: { color: tokens.colorNeutralForeground2 },
});

export function AboutPage() {
  const styles = useStyles();
  const { data, error, loading } = useApi(api.about);

  return (
    <div className={styles.page}>
      <PageHeader title={strings.about.title} lead={strings.about.lead} />
      {loading && <Spinner size="small" />}
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{strings.errors.loadFailed}</MessageBarBody>
        </MessageBar>
      )}
      {data && (
        <Table className={styles.table} aria-label={strings.about.title}>
          <TableBody>
            {Object.entries(strings.about.rows).map(([key, label]) => (
              <TableRow key={key}>
                <TableCell>
                  <Text className={styles.label}>{label}</Text>
                </TableCell>
                <TableCell>
                  <Text weight="semibold">{String(data[key])}</Text>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
