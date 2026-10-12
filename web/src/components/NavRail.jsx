import { Tab, TabList, makeStyles, tokens } from '@fluentui/react-components';
import {
  Home24Filled,
  Home24Regular,
  ChartMultiple24Filled,
  ChartMultiple24Regular,
  DocumentSearch24Filled,
  DocumentSearch24Regular,
  Folder24Filled,
  Folder24Regular,
  Cloud24Filled,
  Cloud24Regular,
  Info24Filled,
  Search24Filled,
  Search24Regular,
  PuzzlePiece24Filled,
  PuzzlePiece24Regular,
  Info24Regular,
  Settings24Filled,
  TextBulletListSquare24Filled,
  TextBulletListSquare24Regular,
  Wallet24Filled,
  Wallet24Regular,
  Settings24Regular,
  bundleIcon,
} from '@fluentui/react-icons';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { strings } from '../strings.js';

const HomeIcon = bundleIcon(Home24Filled, Home24Regular);
const SearchIcon = bundleIcon(Search24Filled, Search24Regular);
const SourcesIcon = bundleIcon(Folder24Filled, Folder24Regular);
const IndexingIcon = bundleIcon(DocumentSearch24Filled, DocumentSearch24Regular);
const CreditsIcon = bundleIcon(Wallet24Filled, Wallet24Regular);
const StatsIcon = bundleIcon(ChartMultiple24Filled, ChartMultiple24Regular);
const AddonsIcon = bundleIcon(PuzzlePiece24Filled, PuzzlePiece24Regular);
const GitHubIcon = bundleIcon(Cloud24Filled, Cloud24Regular);
const LogsIcon = bundleIcon(TextBulletListSquare24Filled, TextBulletListSquare24Regular);
const InfoIcon = bundleIcon(Info24Filled, Info24Regular);
const SettingsIcon = bundleIcon(Settings24Filled, Settings24Regular);

const ITEMS = [
  { path: '/', label: strings.nav.home, icon: <HomeIcon /> },
  { path: '/search', label: strings.nav.search, icon: <SearchIcon /> },
  { path: '/sources', label: strings.nav.sources, icon: <SourcesIcon /> },
  { path: '/indexing', label: strings.nav.indexing, icon: <IndexingIcon /> },
  { path: '/credits', label: strings.nav.credits, icon: <CreditsIcon /> },
  { path: '/stats', label: strings.nav.stats, icon: <StatsIcon /> },
  { path: '/addons', label: strings.nav.addons, icon: <AddonsIcon /> },
  { path: '/github', label: strings.nav.github, icon: <GitHubIcon />, optional: true },
  { path: '/logs', label: strings.nav.logs, icon: <LogsIcon /> },
  { path: '/about', label: strings.nav.about, icon: <InfoIcon /> },
  { path: '/settings', label: strings.nav.settings, icon: <SettingsIcon /> },
];

const useStyles = makeStyles({
  root: {
    width: '220px',
    flexShrink: 0,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalS}`,
  },
  tab: { justifyContent: 'flex-start', width: '100%' },
});

export function NavRail() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [githubOn, setGithubOn] = useState(false);

  // The GitHub page is there only while its add-on is installed, running and allowed.
  useEffect(() => {
    let live = true;
    api.github.availability().then(
      (state) => live && setGithubOn(state.enabled === true),
      () => live && setGithubOn(false),
    );
    return () => {
      live = false;
    };
  }, [pathname]);

  const items = ITEMS.filter((item) => !item.optional || githubOn);
  const selected =
    items.find((item) => item.path !== '/' && pathname.startsWith(item.path))?.path ?? '/';

  return (
    <nav className={styles.root} aria-label="Primary">
      <TabList
        vertical
        size="large"
        selectedValue={selected}
        onTabSelect={(_, data) => navigate(String(data.value))}
      >
        {items.map((item) => (
          <Tab key={item.path} value={item.path} icon={item.icon} className={styles.tab}>
            {item.label}
          </Tab>
        ))}
      </TabList>
    </nav>
  );
}
