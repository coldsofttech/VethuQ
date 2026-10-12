import { makeStyles, tokens } from '@fluentui/react-components';
import { Outlet } from 'react-router-dom';
import { CloseGuard } from './CloseGuard.jsx';
import { DropTarget } from './DropTarget.jsx';
import { NavRail } from './NavRail.jsx';
import { StatusBar } from './StatusBar.jsx';
import { TitleBar } from './TitleBar.jsx';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    background: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
  },
  body: { display: 'flex', flexGrow: 1, minHeight: 0 },
  // Windows 11 style: content sits on a rounded surface above the app background.
  content: {
    flexGrow: 1,
    minWidth: 0,
    overflowY: 'auto',
    margin: `0 ${tokens.spacingHorizontalS} ${tokens.spacingVerticalS} 0`,
    padding: `${tokens.spacingVerticalXXL} ${tokens.spacingHorizontalXXXL}`,
    background: tokens.colorNeutralBackground1,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusXLarge,
    boxShadow: tokens.shadow2,
  },
});

export function AppShell() {
  const styles = useStyles();
  return (
    <div className={styles.root} data-testid="app-shell">
      <TitleBar />
      <div className={styles.body}>
        <NavRail />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
      <StatusBar />
      <CloseGuard />
      <DropTarget />
    </div>
  );
}
