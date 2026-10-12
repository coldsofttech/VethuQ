import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell.jsx';
import { AboutPage } from './pages/AboutPage.jsx';
import { CreditsPage } from './pages/CreditsPage.jsx';
import { AddonsPage } from './pages/AddonsPage.jsx';
import { LogsPage } from './pages/LogsPage.jsx';
import { GitHubPage } from './pages/GitHubPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { IndexingPage } from './pages/IndexingPage.jsx';
import { SearchPage } from './pages/SearchPage.jsx';
import { SettingsPage } from './pages/SettingsPage.jsx';
import { SourceDetailPage } from './pages/SourceDetailPage.jsx';
import { SourcesPage } from './pages/SourcesPage.jsx';
import { StatsPage } from './pages/StatsPage.jsx';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="sources/:id" element={<SourceDetailPage />} />
        <Route path="indexing/*" element={<IndexingPage />} />
        <Route path="credits/*" element={<CreditsPage />} />
        <Route path="stats/*" element={<StatsPage />} />
        <Route path="addons/*" element={<AddonsPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="github/*" element={<GitHubPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="settings/*" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
