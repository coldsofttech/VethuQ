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
  Info24Filled,
  PuzzlePiece24Filled,
  PuzzlePiece24Regular,
  Info24Regular,
  Settings24Filled,
  Wallet24Filled,
  Wallet24Regular,
  Settings24Regular,
  bundleIcon,
} from '@fluentui/react-icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { strings } from '../strings.js';

const HomeIcon = bundleIcon(Home24Filled, Home24Regular);
const SourcesIcon = bundleIcon(Folder24Filled, Folder24Regular);
const IndexingIcon = bundleIcon(DocumentSearch24Filled, DocumentSearch24Regular);
const CreditsIcon = bundleIcon(Wallet24Filled, Wallet24Regular);
const StatsIcon = bundleIcon(ChartMultiple24Filled, ChartMultiple24Regular);
const AddonsIcon = bundleIcon(PuzzlePiece24Filled, PuzzlePiece24Regular);
const InfoIcon = bundleIcon(Info24Filled, Info24Regular);
const SettingsIcon = bundleIcon(Settings24Filled, Settings24Regular);

const ITEMS = [
  { path: '/', label: strings.nav.home, icon: <HomeIcon /> },
  { path: '/sources', label: strings.nav.sources, icon: <SourcesIcon /> },
  { path: '/indexing', label: strings.nav.indexing, icon: <IndexingIcon /> },
  { path: '/credits', label: strings.nav.credits, icon: <CreditsIcon /> },
  { path: '/stats', label: strings.nav.stats, icon: <StatsIcon /> },
  { path: '/addons', label: strings.nav.addons, icon: <AddonsIcon /> },
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
  const selected =
    ITEMS.find((item) => item.path !== '/' && pathname.startsWith(item.path))?.path ?? '/';

  return (
    <nav className={styles.root} aria-label="Primary">
      <TabList
        vertical
        size="large"
        selectedValue={selected}
        onTabSelect={(_, data) => navigate(String(data.value))}
      >
        {ITEMS.map((item) => (
          <Tab key={item.path} value={item.path} icon={item.icon} className={styles.tab}>
            {item.label}
          </Tab>
        ))}
      </TabList>
    </nav>
  );
}
