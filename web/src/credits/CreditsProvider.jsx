import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

const CreditsContext = createContext(null);
const POLL_MS = 30000;

/** What is left of today's credits, kept fresh for the status bar and the Credits pages. */
export function CreditsProvider({ children }) {
  const { version } = useIndexing();
  const [summary, setSummary] = useState(null);
  const [changes, setChanges] = useState(0);

  const refresh = useCallback(() => setChanges((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.credits.summary().then(
        (data) => live && setSummary(data),
        () => {},
      );
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [version, changes]);

  const value = useMemo(() => ({ summary, refresh }), [summary, refresh]);
  return <CreditsContext.Provider value={value}>{children}</CreditsContext.Provider>;
}

export function useCredits() {
  const value = useContext(CreditsContext);
  if (value === null) throw new Error('useCredits needs a CreditsProvider');
  return value;
}
