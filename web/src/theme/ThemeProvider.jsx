import { FluentProvider } from '@fluentui/react-components';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useBrand } from '../brand/BrandProvider.jsx';
import { buildTheme } from './brandTheme.js';

/** @typedef {'system' | 'light' | 'dark'} ThemeChoice */

const STORAGE_KEY = 'vethuq.theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

/** @returns {ThemeChoice} */
function readChoice() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    // Storage can be unavailable; fall back to the system setting.
  }
  return 'system';
}

function systemPrefersDark() {
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK_QUERY).matches;
}

const ThemeContext = createContext({
  choice: /** @type {ThemeChoice} */ ('system'),
  setChoice: /** @type {(choice: ThemeChoice) => void} */ (() => {}),
  isDark: false,
});

export function ThemeProvider({ children }) {
  const [choice, setChoiceState] = useState(readChoice);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const { palette } = useBrand();

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event) => setSystemDark(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const setChoice = useCallback((next) => {
    setChoiceState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisted; the choice still applies for this session.
    }
  }, []);

  const isDark = choice === 'dark' || (choice === 'system' && systemDark);

  useEffect(() => {
    document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
  }, [isDark]);

  const theme = useMemo(
    () => buildTheme(isDark ? 'dark' : 'light', palette?.[isDark ? 'dark' : 'light']),
    [isDark, palette],
  );

  const value = useMemo(() => ({ choice, setChoice, isDark }), [choice, setChoice, isDark]);

  return (
    <ThemeContext.Provider value={value}>
      <FluentProvider theme={theme} style={{ height: '100%', background: 'transparent' }}>
        {children}
      </FluentProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
