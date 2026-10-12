import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { App } from './App.jsx';
import { PlatformProvider } from './platform/PlatformProvider.jsx';
import './styles.css';
import { ThemeProvider } from './theme/ThemeProvider.jsx';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <PlatformProvider>
        <HashRouter>
          <App />
        </HashRouter>
      </PlatformProvider>
    </ThemeProvider>
  </StrictMode>,
);
