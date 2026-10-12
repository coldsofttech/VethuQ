import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { useNotify } from '../components/Notifications.jsx';

const IndexingContext = createContext(null);

const IDLE_MS = 3000;
const ACTIVE_MS = 1000;
const REFRESH_MS = 30000; // finished remote results are taken in this often
const RELOAD_MS = 5000; // lists reload this often while a run goes

/** What a run's end says, as a toast. */
function summary(run) {
  const failed = run.files_failed ? `, ${run.files_failed} failed` : '';
  const counts = `${run.files_processed} of ${run.files_total} files read${failed}`;
  switch (run.status) {
    case 'completed':
      return {
        title: 'Indexing finished',
        body: counts,
        intent: run.files_failed ? 'warning' : 'success',
      };
    case 'stopped':
      return { title: 'Indexing stopped', body: counts, intent: 'info' };
    case 'failed':
      return { title: 'Indexing failed', body: run.error || counts, intent: 'error' };
    case 'waiting_credits':
      return {
        title: 'Out of credits',
        body: 'Indexing carries on after the credits reset at 00:00 UTC.',
        intent: 'warning',
      };
    case 'waiting_remote':
      return {
        title: 'Waiting for GitHub',
        body: 'Results are collected as they arrive.',
        intent: 'info',
      };
    default:
      return null;
  }
}

/**
 * The state of indexing for the whole window: polled all the time (so runs started by the command
 * line or the background service show too), plus the actions on it. `version` goes up when lists on
 * screen should load again.
 */
export function IndexingProvider({ children }) {
  const notify = useNotify();
  const [state, setState] = useState(
    /** @type {import('../api/client.js').IndexState | null} */ (null),
  );
  const [version, setVersion] = useState(0);
  const [asking, setAsking] = useState(false);
  const [stopping, setStopping] = useState(false);
  const seen = useRef(/** @type {{ id?: number, status?: string } | null} */ (null));
  const lastReload = useRef(0);
  const busy = useRef(false);

  const bump = useCallback(() => {
    lastReload.current = Date.now();
    setVersion((current) => current + 1);
  }, []);

  const apply = useCallback(
    (next) => {
      setState(next);
      busy.current = next.active || next.runner.mode === 'one-off' || next.queued > 0;
      const run = next.run;
      const before = seen.current;
      seen.current = run ? { id: run.id, status: run.status } : null;
      const changed = run && (!before || before.id !== run.id || before.status !== run.status);
      if (changed && before) {
        const message = summary(run);
        if (message && run.status !== 'running') notify(message);
      }
      if (changed || (next.active && Date.now() - lastReload.current > RELOAD_MS)) bump();
    },
    [notify, bump],
  );

  useEffect(() => {
    let stopped = false;
    let timer;
    const tick = async () => {
      try {
        apply(await api.index.state());
      } catch {
        // The service is not answering; the next tick tries again.
      }
      if (!stopped) timer = setTimeout(tick, busy.current ? ACTIVE_MS : IDLE_MS);
    };
    tick();
    const collect = setInterval(() => {
      api.index.refresh().then(apply, () => {});
    }, REFRESH_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(collect);
    };
  }, [apply]);

  const refresh = useCallback(async () => {
    try {
      apply(await api.index.refresh());
    } catch (error) {
      notify({ title: 'Could not refresh', body: error.message, intent: 'error' });
    }
    bump();
  }, [apply, notify, bump]);

  const act = useCallback(
    async (call, failure) => {
      try {
        apply(await call());
        return true;
      } catch (error) {
        notify({ title: failure, body: error.message, intent: 'error' });
        return false;
      }
    },
    [apply, notify],
  );

  const start = useCallback(
    async (mode, target = null) => {
      const ok = await act(() => api.index.start(mode, target), 'Could not start indexing');
      if (ok) bump();
      return ok;
    },
    [act, bump],
  );

  const confirmStop = async () => {
    setStopping(true);
    await act(() => api.index.stop(), 'Could not stop indexing');
    setStopping(false);
    setAsking(false);
  };

  const value = useMemo(
    () => ({
      state,
      version,
      bump,
      refresh,
      start,
      pause: () => act(() => api.index.pause(), 'Could not pause'),
      resume: () => act(() => api.index.resume(), 'Could not resume'),
      requestStop: () => setAsking(true),
      serviceAction: (action) =>
        act(() => api.service.perform(action), `Could not ${action} the service`),
    }),
    [state, version, bump, refresh, start, act],
  );

  return (
    <IndexingContext.Provider value={value}>
      {children}
      <ConfirmDialog
        open={asking}
        title="Stop indexing?"
        confirmLabel="Stop indexing"
        cancelLabel="Keep going"
        busy={stopping}
        onConfirm={confirmStop}
        onCancel={() => setAsking(false)}
      >
        The run ends after the file it is on. Files keep the pages already read, and the next run
        carries on from there.
      </ConfirmDialog>
    </IndexingContext.Provider>
  );
}

export function useIndexing() {
  const value = useContext(IndexingContext);
  if (value === null) throw new Error('useIndexing needs an IndexingProvider');
  return value;
}
