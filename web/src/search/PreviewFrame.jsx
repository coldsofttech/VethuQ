import { Text, makeStyles, tokens } from '@fluentui/react-components';
import { ChevronDown20Regular, ChevronUp20Regular, Dismiss20Regular } from '@fluentui/react-icons';
import { ToolButton } from '../components/ToolButton.jsx';

const useStyles = makeStyles({
  panel: {
    display: 'flex',
    flexDirection: 'column',
    minHeight: 0,
    height: '100%',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    overflow: 'hidden',
  },
  head: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalXS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  name: {
    flex: '1 1 140px',
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  muted: { color: tokens.colorNeutralForeground3, whiteSpace: 'nowrap' },
});

/**
 * The frame the previews share: the file's name, where the match is, buttons to step through the
 * file's matches, the preview's own tools, and close.
 *
 * @param {object} props
 * @param {string} props.label The region's accessible name.
 * @param {{file_name: string, file_path: string}} props.match The match shown.
 * @param {number} props.index
 * @param {number} props.count How many matches the file has.
 * @param {string} props.place Where the match is, e.g. "page 3 of 12".
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 * @param {import('react').ReactNode} [props.tools] More buttons, before close.
 */
export function PreviewFrame({
  label,
  match,
  index,
  count,
  place,
  onIndex,
  onClose,
  tools,
  children,
}) {
  const styles = useStyles();
  return (
    <section className={styles.panel} aria-label={label}>
      <div className={styles.head}>
        <Text weight="semibold" className={styles.name} title={match.file_path}>
          {match.file_name}
        </Text>
        <Text className={styles.muted}>
          Match {index + 1} of {count} · {place}
        </Text>
        <ToolButton
          label="Previous match"
          icon={<ChevronUp20Regular />}
          appearance="subtle"
          disabled={index === 0}
          onClick={() => onIndex(index - 1)}
        />
        <ToolButton
          label="Next match"
          icon={<ChevronDown20Regular />}
          appearance="subtle"
          disabled={index >= count - 1}
          onClick={() => onIndex(index + 1)}
        />
        {tools}
        <ToolButton
          label="Close preview"
          icon={<Dismiss20Regular />}
          appearance="subtle"
          onClick={onClose}
        />
      </div>
      {children}
    </section>
  );
}
