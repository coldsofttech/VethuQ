import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const FOLLOW_MS = 2000;

/**
 * The entries of one log for some filters. Following (oldest first only) asks for what came after
 * the entries already held, and appends them.
 */
export function useLogEntries({ component, day, level, contains, order, follow, refresh }) {
  const [state, setState] = useState({
    items: [],
    total: 0,
    exists: true,
    loading: true,
    error: null,
  });
  const total = useRef(0);

  const params = { day, level, contains, order, limit: 500 };

  useEffect(() => {
    const controller = new AbortController();
    // Reading starts again when a filter changes; what comes back fills the list.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, loading: true }));
    api.logs.entries(component, params, controller.signal).then(
      (data) => {
        total.current = data.total;
        setState({
          items: data.items,
          total: data.total,
          exists: data.exists,
          loading: false,
          error: null,
        });
      },
      (error) => error?.name !== 'AbortError' && setState((s) => ({ ...s, loading: false, error })),
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [component, day, level, contains, order, refresh]);

  const poll = useCallback(async () => {
    try {
      const data = await api.logs.entries(component, { ...params, after: total.current });
      if (data.items.length === 0 && data.total === total.current) return;
      total.current = data.total;
      setState((s) => ({
        ...s,
        items: [...s.items, ...data.items],
        total: data.total,
        exists: data.exists,
      }));
    } catch {
      // The next tick tries again.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [component, day, level, contains, order]);

  useEffect(() => {
    if (!follow || order !== 'asc') return undefined;
    const timer = setInterval(poll, FOLLOW_MS);
    return () => clearInterval(timer);
  }, [follow, order, poll]);

  return state;
}
