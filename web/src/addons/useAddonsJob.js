import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const IDLE = { running: false, action: null, target: null, log: [], error: null, finished: false };

/** The install or update that is going: starts it and polls until it ends; `onDone(job)` once. */
export function useAddonsJob(onDone) {
  const [job, setJob] = useState(IDLE);
  const done = useRef(onDone);
  const wasRunning = useRef(false);

  useEffect(() => {
    done.current = onDone;
  }, [onDone]);

  const apply = useCallback((next) => {
    setJob(next);
    if (wasRunning.current && !next.running) done.current?.(next);
    wasRunning.current = next.running;
  }, []);

  useEffect(() => {
    let live = true;
    let timer;
    const tick = async () => {
      try {
        const next = await api.addons.job();
        if (live) apply(next);
        if (live && next.running) timer = setTimeout(tick, 1500);
      } catch {
        // Not answering; the next start or visit looks again.
      }
    };
    tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [apply, job.running]);

  const run = useCallback(
    async (call) => {
      const next = await call();
      apply(next);
      return next;
    },
    [apply],
  );

  return { job, run };
}
