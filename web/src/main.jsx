import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { App } from './App.jsx';
import { BrandProvider } from './brand/BrandProvider.jsx';
import { NotifyProvider } from './components/Notifications.jsx';
import { IndexingProvider } from './indexing/IndexingProvider.jsx';
import { PlatformProvider } from './platform/PlatformProvider.jsx';
import './styles.css';
import { ThemeProvider } from './theme/ThemeProvider.jsx';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrandProvider>
      <ThemeProvider>
        <PlatformProvider>
          <NotifyProvider>
            <IndexingProvider>
              <HashRouter>
                <App />
              </HashRouter>
            </IndexingProvider>
          </NotifyProvider>
        </PlatformProvider>
      </ThemeProvider>
    </BrandProvider>
  </StrictMode>,
);
