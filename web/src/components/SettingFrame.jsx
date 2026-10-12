import { Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  row: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) minmax(220px, 300px)',
    gap: tokens.spacingHorizontalXXL,
    alignItems: 'start',
    padding: `${tokens.spacingVerticalM} 0`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  stacked: { gridTemplateColumns: 'minmax(0, 1fr)', gap: tokens.spacingVerticalS },
  about: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS },
  hint: { color: tokens.colorNeutralForeground3 },
});

/**
 * The layout every setting shares: what it is on the left, its control on the right (or below,
 * for a wide control).
 */
export function SettingFrame({ label, description, hint, stacked, testId, children }) {
  const styles = useStyles();
  return (
    <div className={`${styles.row} ${stacked ? styles.stacked : ''}`} data-testid={testId}>
      <div className={styles.about}>
        <Text weight="semibold">{label}</Text>
        {description && <Text className={styles.hint}>{description}</Text>}
        {hint && (
          <Text size={200} className={styles.hint}>
            {hint}
          </Text>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}
