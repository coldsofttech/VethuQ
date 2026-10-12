import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const IDLE = { running: false, action: null, progress: {}, error: null, finished: false };

/**
 * The model download job: starts it, and polls while it runs. `onDone(job)` is called once when a
 * job that was running ends (also one that was already going when the page opened).
 */
export function useOcrJob(onDone) {
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
        const next = await api.ocr.job();
        if (live) apply(next);
        if (live && next.running) timer = setTimeout(tick, 1000);
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

  const start = useCallback(
    async (action, body) => {
      const next = await api.ocr.start(action, body);
      apply(next);
      return next;
    },
    [apply],
  );

  return { job, start };
}
