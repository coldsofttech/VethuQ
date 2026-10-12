import { Subtitle1, Body1, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXS },
  lead: { color: tokens.colorNeutralForeground2 },
});

export function PageHeader({ title, lead }) {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      <Subtitle1 as="h1">{title}</Subtitle1>
      {lead && <Body1 className={styles.lead}>{lead}</Body1>}
    </div>
  );
}
