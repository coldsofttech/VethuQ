import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell.jsx';
import { AboutPage } from './pages/AboutPage.jsx';
import { CreditsPage } from './pages/CreditsPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { IndexingPage } from './pages/IndexingPage.jsx';
import { SettingsPage } from './pages/SettingsPage.jsx';
import { SourceDetailPage } from './pages/SourceDetailPage.jsx';
import { SourcesPage } from './pages/SourcesPage.jsx';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="sources/:id" element={<SourceDetailPage />} />
        <Route path="indexing/*" element={<IndexingPage />} />
        <Route path="credits/*" element={<CreditsPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="settings/*" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
