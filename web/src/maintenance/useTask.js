import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const IDLE = { running: false, result: null, error: null, finished: false };

/**
 * A slow job on the service ("db-check", "search-rebuild"): started with `start(call)`, polled while it
 * runs. `onDone(state)` is called once when a job that was going ends.
 */
export function useTask(name, onDone) {
  const [state, setState] = useState(IDLE);
  const done = useRef(onDone);
  const wasRunning = useRef(false);

  useEffect(() => {
    done.current = onDone;
  }, [onDone]);

  const apply = useCallback((next) => {
    setState(next);
    if (wasRunning.current && !next.running) done.current?.(next);
    wasRunning.current = next.running;
  }, []);

  useEffect(() => {
    let live = true;
    let timer;
    const tick = async () => {
      try {
        const all = await api.maintenance.tasks();
        if (live) apply(all[name] ?? IDLE);
        if (live && all[name]?.running) timer = setTimeout(tick, 1000);
      } catch {
        // Not answering; the next visit looks again.
      }
    };
    tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [name, apply, state.running]);

  const start = useCallback(
    async (call) => {
      const next = await call();
      apply(next);
      return next;
    },
    [apply],
  );

  return { task: state, start };
}
