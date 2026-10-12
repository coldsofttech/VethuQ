import {
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  ProgressBar,
  Text,
  Tooltip,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowSync20Regular,
  Pause16Regular,
  Play16Regular,
  Stop16Regular,
} from '@fluentui/react-icons';
import { useNavigate } from 'react-router-dom';
import { baseName, formatDuration } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: tokens.spacingHorizontalL,
    height: '28px',
    flexShrink: 0,
    padding: `0 ${tokens.spacingHorizontalM}`,
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
    background: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground2,
  },
  right: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, minWidth: 0 },
  strip: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
    minWidth: 0,
    cursor: 'pointer',
    background: 'transparent',
    border: 'none',
    color: 'inherit',
    padding: 0,
    font: 'inherit',
  },
  label: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '280px' },
  bar: { width: '110px' },
  dot: {
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    border: 'none',
    padding: 0,
    cursor: 'pointer',
    display: 'inline-block',
  },
  green: { background: tokens.colorPaletteGreenForeground1 },
  amber: { background: tokens.colorPaletteMarigoldBackground3 },
  red: { background: tokens.colorPaletteRedBackground3 },
  grey: { background: tokens.colorNeutralForeground4 },
});

const VERBS = {
  run: 'Indexing',
  restart: 'Retrying failed files in',
  reindex: 'Reindexing',
  file: 'Reindexing',
};

/** What the strip says about the run that is going (or waiting). */
export function describe(state) {
  const run = state.run;
  if (!state.active && state.queued > 0) {
    return { text: 'Queued for the background service', progress: null };
  }
  if (!run || !(state.active || state.runner.mode === 'one-off')) return null;
  if (!state.active) return { text: 'Starting indexing…', progress: null };
  const target = run.target ? baseName(run.target) : 'all sources';
  const total = run.files_total || 0;
  const counts = `${run.files_processed}/${total} files${run.files_failed ? ` · ${run.files_failed} failed` : ''}`;
  const eta =
    state.eta && state.eta.seconds > 0 ? ` · about ${formatDuration(state.eta.seconds)} left` : '';
  const prefix = state.paused ? 'Paused: ' : state.stopping ? 'Stopping: ' : '';
  return {
    text: `${prefix}${VERBS[run.mode] ?? 'Indexing'} ${target} · ${counts}${eta}`,
    progress: total ? run.files_processed / total : null,
  };
}

function waiting(state) {
  const status = state.run?.status;
  if (state.active || !state.run) return null;
  if (status === 'waiting_credits') return 'Waiting for credits (they reset at 00:00 UTC)';
  if (status === 'waiting_remote') return `Waiting for GitHub results (${state.remote_jobs_open})`;
  return null;
}

/** The Windows-style bar at the bottom: what indexing is doing, and the background service. */
export function StatusBar() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { state, pause, resume, requestStop, serviceAction } = useIndexing();
  if (!state) return <footer className={styles.root} data-testid="status-bar" />;

  const shown = describe(state);
  const idleNote = waiting(state);
  const service = state.service;

  return (
    <footer className={styles.root} data-testid="status-bar">
      <Text size={200}>{shown ? 'Indexing' : idleNote || 'Ready'}</Text>
      <div className={styles.right}>
        {shown && (
          <>
            <button
              type="button"
              className={styles.strip}
              onClick={() => navigate('/indexing')}
              aria-label="Show indexing activity"
            >
              <ArrowSync20Regular />
              <Text size={200} className={styles.label} title={shown.text}>
                {shown.text}
              </Text>
              {shown.progress !== null && (
                <ProgressBar className={styles.bar} thickness="medium" value={shown.progress} />
              )}
            </button>
            {state.active && (
              <>
                <Tooltip content={state.paused ? 'Resume' : 'Pause'} relationship="label">
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={state.paused ? <Play16Regular /> : <Pause16Regular />}
                    onClick={state.paused ? resume : pause}
                  />
                </Tooltip>
                <Tooltip content="Stop" relationship="label">
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<Stop16Regular />}
                    disabled={state.stopping}
                    onClick={requestStop}
                  />
                </Tooltip>
              </>
            )}
          </>
        )}
        {service && (
          <Menu openOnContext>
            <MenuTrigger disableButtonEnhancement>
              <Tooltip content={`${service.label}: ${service.tooltip}`} relationship="description">
                <button
                  type="button"
                  className={mergeClasses(styles.dot, styles[service.colour])}
                  aria-label={`Background service: ${service.label}`}
                  data-testid="service-dot"
                  onClick={() => navigate('/indexing')}
                />
              </Tooltip>
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem
                  disabled={service.state !== 'STOPPED'}
                  onClick={() => serviceAction('start')}
                >
                  Start the service
                </MenuItem>
                <MenuItem
                  disabled={service.state === 'STOPPED'}
                  onClick={() => serviceAction('stop')}
                >
                  Stop the service
                </MenuItem>
                <MenuItem
                  disabled={service.state !== 'RUNNING'}
                  onClick={() => serviceAction('pause')}
                >
                  Pause the service
                </MenuItem>
                <MenuItem
                  disabled={service.state !== 'PAUSED'}
                  onClick={() => serviceAction('resume')}
                >
                  Resume the service
                </MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        )}
      </div>
    </footer>
  );
}
