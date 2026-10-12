import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  dot: {
    width: '12px',
    height: '12px',
    flexShrink: 0,
    borderRadius: '50%',
    display: 'inline-block',
    border: 'none',
    padding: 0,
  },
  green: { background: tokens.colorPaletteGreenForeground1 },
  amber: { background: tokens.colorPaletteMarigoldBackground3 },
  red: { background: tokens.colorPaletteRedBackground3 },
  grey: { background: tokens.colorNeutralForeground4 },
});

/** The small circle for the background service: green idle, amber working, red error, grey stopped. */
export function ServiceDot({ colour, className, ...props }) {
  const styles = useStyles();
  return <span {...props} className={mergeClasses(styles.dot, styles[colour], className)} />;
}
