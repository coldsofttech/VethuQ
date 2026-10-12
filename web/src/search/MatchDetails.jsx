import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { FoundBy, Snippet } from './ResultsList.jsx';

const useStyles = makeStyles({
  facts: {
    display: 'grid',
    gridTemplateColumns: 'max-content 1fr',
    gap: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalL}`,
  },
  muted: { color: tokens.colorNeutralForeground3 },
  snippet: {
    display: 'block',
    padding: tokens.spacingVerticalM,
    margin: `${tokens.spacingVerticalM} 0`,
    background: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    overflowWrap: 'anywhere',
  },
  hit: { background: tokens.colorPaletteYellowBackground2, color: tokens.colorNeutralForeground1 },
});

/** Everything the core knows about one match. */
export function MatchDetails({ match, labels, onClose }) {
  const styles = useStyles();
  return (
    <Dialog open={match !== null} onOpenChange={(_, data) => !data.open && onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{match?.file_name}</DialogTitle>
          <DialogContent>
            {match && (
              <>
                <Snippet match={match} className={styles.snippet} hitClass={styles.hit} />
                <div className={styles.facts}>
                  <Text className={styles.muted}>Path</Text>
                  <Text>{match.file_path}</Text>
                  <Text className={styles.muted}>File type</Text>
                  <Text>{match.file_type ?? 'unknown'}</Text>
                  <Text className={styles.muted}>Page</Text>
                  <Text>
                    {match.page_number} of {match.total_pages}
                  </Text>
                  {match.line != null && (
                    <>
                      <Text className={styles.muted}>Line</Text>
                      <Text>
                        {match.line}
                        {match.column != null ? `, column ${match.column}` : ''}
                      </Text>
                    </>
                  )}
                  <Text className={styles.muted}>Page read</Text>
                  <Text>{match.source}</Text>
                  <Text className={styles.muted}>Found by</Text>
                  <FoundBy match={match} labels={labels} />
                  {match.modifiers.length > 0 && (
                    <>
                      <Text className={styles.muted}>Needed</Text>
                      <Text>{match.modifiers.join(', ')}</Text>
                    </>
                  )}
                  {match.score != null && (
                    <>
                      <Text className={styles.muted}>Score</Text>
                      <Text>{Math.round(match.score * 100)}%</Text>
                    </>
                  )}
                  {match.duplicate_of_path && (
                    <>
                      <Text className={styles.muted}>Duplicate of</Text>
                      <Text>{match.duplicate_of_path}</Text>
                    </>
                  )}
                </div>
              </>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={onClose}>
              Close
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
