import {
  Badge,
  Menu,
  MenuDivider,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Text,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  Copy20Regular,
  DocumentArrowRight20Regular,
  Eye20Regular,
  FolderArrowRight20Regular,
  FolderOpen20Regular,
  Info20Regular,
  ArrowSync20Regular,
} from '@fluentui/react-icons';
import { FileIcon } from '../components/FileIcon.jsx';
import { baseName } from '../format.js';
import { canPreview, describePlace, placeOf } from './form.js';

const useStyles = makeStyles({
  table: {
    display: 'flex',
    flexDirection: 'column',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  head: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 90px 200px 80px',
    gap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    background: tokens.colorNeutralBackground2,
    color: tokens.colorNeutralForeground3,
    fontWeight: tokens.fontWeightSemibold,
  },
  file: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    background: tokens.colorNeutralBackground3,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    cursor: 'default',
  },
  folder: { color: tokens.colorNeutralForeground3 },
  match: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 90px 200px 80px',
    gap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalM}`,
    borderTop: `1px solid ${tokens.colorNeutralStroke3}`,
    alignItems: 'baseline',
    cursor: 'default',
    ':hover': { background: tokens.colorNeutralBackground1Hover },
  },
  compact: { gridTemplateColumns: 'minmax(0, 1fr) 70px' },
  snippet: { overflowWrap: 'anywhere', lineHeight: tokens.lineHeightBase300 },
  hit: {
    background: tokens.colorPaletteYellowBackground2,
    color: tokens.colorNeutralForeground1,
    borderRadius: '2px',
    padding: '0 1px',
  },
  found: { display: 'flex', gap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
  grow: { flexGrow: 1 },
});

const APPROXIMATE = new Set(['fuzzy', 'noise-fuzzy', 'semantic']);

/** The text around a match with the match marked. */
export function Snippet({ match, className, hitClass }) {
  return (
    <span className={className}>
      {match.truncated_before ? '… ' : ''}
      {match.before}
      <mark className={hitClass}>{match.matched}</mark>
      {match.after}
      {match.truncated_after ? ' …' : ''}
    </span>
  );
}

/** How a match was found: its engine, any others that found it, and its score when the engine guesses. */
export function FoundBy({ match, labels }) {
  const styles = useStyles();
  const label = (id) => labels[id] ?? id;
  const percent =
    match.score != null && APPROXIMATE.has(match.engine)
      ? ` ${Math.round(match.score * 100)}%`
      : '';
  const also = match.matched_by.filter((id) => id !== match.engine);
  const title = [
    also.length ? `Also found by ${also.map(label).join(', ')}` : '',
    match.modifiers.length ? `Needed: ${match.modifiers.join(', ')}` : '',
  ]
    .filter(Boolean)
    .join('. ');
  return (
    <span className={styles.found} title={title || undefined}>
      <Badge appearance="tint" color="brand">
        {label(match.engine)}
        {percent}
      </Badge>
      {also.length > 0 && (
        <Badge appearance="outline" color="informative">
          +{also.length}
        </Badge>
      )}
    </span>
  );
}

const group = (matches) => {
  const groups = [];
  for (const match of matches) {
    const last = groups.at(-1);
    if (last && last.path === match.file_path) last.matches.push(match);
    else groups.push({ path: match.file_path, first: match, matches: [match] });
  }
  return groups;
};

/** The menu a result opens with a right-click, for the file (and, on a match, for that match). */
function ResultMenu({ match, actions, platform, onlyFile }) {
  return (
    <MenuList>
      <MenuItem
        icon={<DocumentArrowRight20Regular />}
        disabled={!platform.openFile}
        title={describePlace(placeOf(match)) ?? undefined}
        onClick={() => actions.open(match)}
      >
        Open
      </MenuItem>
      <MenuItem
        icon={<Eye20Regular />}
        disabled={!canPreview(match)}
        title={
          canPreview(match)
            ? undefined
            : 'Preview is for PDF, text, Markdown, CSV, TSV, Parquet, CSS, HTML, MHTML, JSON, NDJSON, YAML, JS, XML and picture files for now'
        }
        onClick={() => actions.preview(match)}
      >
        Preview
      </MenuItem>
      {platform.reveal && (
        <MenuItem icon={<FolderOpen20Regular />} onClick={() => actions.reveal(match)}>
          Show in Explorer
        </MenuItem>
      )}
      <MenuItem
        icon={<FolderArrowRight20Regular />}
        disabled={!actions.hasSource(match)}
        onClick={() => actions.openInSources(match)}
      >
        Open in Sources
      </MenuItem>
      <MenuDivider />
      <MenuItem
        icon={<Copy20Regular />}
        onClick={() => actions.copy(match.file_path, 'Path copied')}
      >
        Copy path
      </MenuItem>
      {!onlyFile && (
        <>
          <MenuItem
            icon={<Copy20Regular />}
            onClick={() => actions.copy(match.matched, 'Match copied')}
          >
            Copy match text
          </MenuItem>
          <MenuItem
            icon={<Copy20Regular />}
            onClick={() =>
              actions.copy(`${match.before}${match.matched}${match.after}`, 'Snippet copied')
            }
          >
            Copy snippet
          </MenuItem>
          <MenuItem icon={<Info20Regular />} onClick={() => actions.details(match)}>
            Details
          </MenuItem>
        </>
      )}
      <MenuDivider />
      <MenuItem icon={<ArrowSync20Regular />} onClick={() => actions.reindex(match)}>
        Reindex this file
      </MenuItem>
    </MenuList>
  );
}

/**
 * The matches, one block per file: the file's icon, name and folder, then a row for each match with its
 * page, the text around it, how it was found and how the page was read. A right-click on a file or a
 * match opens the menu; a double-click opens the file.
 */
export function ResultsList({ matches, labels, actions, platform, compact = false }) {
  const styles = useStyles();
  return (
    <div className={styles.table} role="table" aria-label="Search results">
      <div className={mergeClasses(styles.head, compact && styles.compact)} role="row">
        <span role="columnheader">Match</span>
        <span role="columnheader">Page</span>
        {!compact && <span role="columnheader">Found by</span>}
        {!compact && <span role="columnheader">Read</span>}
      </div>
      {group(matches).map((g) => (
        <div key={`${g.path}-${g.first.page_number}-${g.first.start}`} role="rowgroup">
          <Menu openOnContext>
            <MenuTrigger disableButtonEnhancement>
              <div className={styles.file} role="row" onDoubleClick={() => actions.open(g.first)}>
                <FileIcon file={{ file_type: g.first.file_type, protected: false }} />
                <Text weight="semibold">{g.first.file_name}</Text>
                <Text
                  size={200}
                  className={mergeClasses(styles.folder, styles.grow)}
                  title={g.path}
                >
                  {g.path.slice(0, Math.max(0, g.path.length - g.first.file_name.length)) ||
                    baseName(g.path)}
                </Text>
                {g.first.duplicate_of_path && (
                  <Badge
                    appearance="outline"
                    color="informative"
                    title={`Same content as ${g.first.duplicate_of_path}`}
                  >
                    duplicate
                  </Badge>
                )}
                <Text size={200} className={styles.folder}>
                  {g.matches.length} {g.matches.length === 1 ? 'match' : 'matches'}
                </Text>
              </div>
            </MenuTrigger>
            <MenuPopover>
              <ResultMenu match={g.first} actions={actions} platform={platform} onlyFile />
            </MenuPopover>
          </Menu>
          {g.matches.map((match) => (
            <Menu key={`${match.page_number}-${match.start}-${match.engine}`} openOnContext>
              <MenuTrigger disableButtonEnhancement>
                <div
                  className={mergeClasses(styles.match, compact && styles.compact)}
                  role="row"
                  onDoubleClick={() => actions.open(match)}
                >
                  <Snippet match={match} className={styles.snippet} hitClass={styles.hit} />
                  <Text role="cell">
                    {match.page_number} of {match.total_pages}
                  </Text>
                  {!compact && (
                    <span role="cell">
                      <FoundBy match={match} labels={labels} />
                    </span>
                  )}
                  {!compact && (
                    <Text role="cell" className={styles.folder}>
                      {match.source}
                    </Text>
                  )}
                </div>
              </MenuTrigger>
              <MenuPopover>
                <ResultMenu match={match} actions={actions} platform={platform} />
              </MenuPopover>
            </Menu>
          ))}
        </div>
      ))}
    </div>
  );
}
