import { Text, Tooltip, makeStyles, tokens } from '@fluentui/react-components';
import { Wallet16Regular } from '@fluentui/react-icons';
import { useNavigate } from 'react-router-dom';
import { useCredits } from '../credits/CreditsProvider.jsx';
import { walletLabel } from '../credits/labels.js';
import { formatCredits } from '../format.js';

const useStyles = makeStyles({
  button: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalXS,
    background: 'transparent',
    border: 'none',
    padding: 0,
    cursor: 'pointer',
    color: 'inherit',
    font: 'inherit',
  },
  ok: {},
  low: { color: tokens.colorPaletteMarigoldForeground1 },
  empty: { color: tokens.colorPaletteRedForeground1 },
});

/** What is left of today's credits, at the right end of the status bar. */
export function CreditsStatus() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { summary } = useCredits();
  if (!summary?.primary) return null;

  const tooltip = [
    ...summary.wallets.map(
      (w) =>
        `${walletLabel(w.wallet)}: ${formatCredits(w.daily)} of ${formatCredits(w.daily_allowance)} today, ${formatCredits(w.total)} available`,
    ),
  ].join('\n');
  const text =
    summary.level === 'empty'
      ? "Today's credits used"
      : `${formatCredits(summary.daily)} credits left today`;

  return (
    <Tooltip
      content={<span style={{ whiteSpace: 'pre-line' }}>{tooltip}</span>}
      relationship="description"
    >
      <button
        type="button"
        className={`${styles.button} ${styles[summary.level] ?? ''}`}
        data-testid="credits-status"
        aria-label={`Credits: ${text}`}
        onClick={() => navigate('/credits')}
      >
        <Wallet16Regular />
        <Text size={200}>{text}</Text>
      </button>
    </Tooltip>
  );
}
