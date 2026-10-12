import { Subtitle2, Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
    paddingTop: tokens.spacingVerticalL,
  },
  note: { color: tokens.colorNeutralForeground3 },
});

/** A heading over a run of related settings, with an optional line under it. */
export function GroupHeading({ title, note }) {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      <Subtitle2 as="h2">{title}</Subtitle2>
      {note && <Text className={styles.note}>{note}</Text>}
    </div>
  );
}
