import { Text, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import {
  Dismiss16Regular,
  Square16Regular,
  SquareMultiple16Regular,
  Subtract16Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { strings } from '../strings.js';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'stretch',
    height: '32px',
    flexShrink: 0,
    userSelect: 'none',
  },
  // pywebview turns elements with the `pywebview-drag-region` class into the window drag handle.
  // Children ignore the pointer so the mouse-down target is always the region itself.
  drag: {
    display: 'flex',
    alignItems: 'center',
    flexGrow: 1,
    gap: tokens.spacingHorizontalS,
    paddingLeft: tokens.spacingHorizontalM,
    '& > *': { pointerEvents: 'none' },
  },
  logo: { width: '16px', height: '16px' },
  controls: { display: 'flex' },
  control: {
    width: '46px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: 'none',
    background: 'transparent',
    color: tokens.colorNeutralForeground1,
    cursor: 'default',
    ':hover': { background: tokens.colorSubtleBackgroundHover },
    ':active': { background: tokens.colorSubtleBackgroundPressed },
    ':focus-visible': { outline: `2px solid ${tokens.colorStrokeFocus2}`, outlineOffset: '-2px' },
  },
  close: {
    ':hover': { background: '#c42b1c', color: '#ffffff' },
    ':active': { background: '#b22a1b', color: '#ffffff' },
  },
});

export function TitleBar() {
  const styles = useStyles();
  const { windowControls } = usePlatform();
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!windowControls) return undefined;
    let cancelled = false;
    const sync = () =>
      api.window.state().then(
        (state) => !cancelled && setMaximized(state.maximized),
        () => {},
      );
    sync();
    // The user can also maximise with the keyboard or by snapping, so follow the window.
    window.addEventListener('resize', sync);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', sync);
    };
  }, [windowControls]);

  const perform = useCallback(
    (action) =>
      api.window.perform(action).then(
        (state) => setMaximized(state.maximized),
        () => {},
      ),
    [],
  );

  const toggleMaximize = () => perform(maximized ? 'restore' : 'maximize');

  return (
    <header className={styles.root} data-testid="title-bar">
      <div
        className={mergeClasses(styles.drag, 'pywebview-drag-region')}
        onDoubleClick={windowControls ? toggleMaximize : undefined}
      >
        <img className={styles.logo} src="/icon.svg" alt="" />
        <Text size={200}>{strings.appName}</Text>
      </div>
      {windowControls && (
        <div className={styles.controls}>
          <button
            type="button"
            className={styles.control}
            aria-label={strings.window.minimize}
            onClick={() => perform('minimize')}
          >
            <Subtract16Regular />
          </button>
          <button
            type="button"
            className={styles.control}
            aria-label={maximized ? strings.window.restore : strings.window.maximize}
            onClick={toggleMaximize}
          >
            {maximized ? <SquareMultiple16Regular /> : <Square16Regular />}
          </button>
          <button
            type="button"
            className={mergeClasses(styles.control, styles.close)}
            aria-label={strings.window.close}
            onClick={() => perform('close')}
          >
            <Dismiss16Regular />
          </button>
        </div>
      )}
    </header>
  );
}
