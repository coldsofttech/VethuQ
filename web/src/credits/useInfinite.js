import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Pages of a list that grow as it scrolls. `load(offset, signal)` answers `{ items, total?, more? }`;
 * the list starts again whenever `deps` change.
 */
export function useInfinite(load, deps) {
  const [state, setState] = useState({
    items: [],
    total: null,
    more: false,
    loading: true,
    error: null,
  });
  const token = useRef(0);
  const loaded = useRef(0);

  const fetchPage = useCallback(
    async (offset, signal) => {
      const mine = ++token.current;
      setState((s) => ({ ...s, loading: true }));
      try {
        const page = await load(offset, signal);
        if (mine !== token.current) return;
        loaded.current = offset + page.items.length;
        setState((s) => {
          const items = offset === 0 ? page.items : [...s.items, ...page.items];
          const total = page.total ?? null;
          return {
            items,
            total,
            more: page.more ?? (total !== null && items.length < total),
            loading: false,
            error: null,
          };
        });
      } catch (error) {
        if (error?.name !== 'AbortError' && mine === token.current)
          setState((s) => ({ ...s, loading: false, error }));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    deps,
  );

  useEffect(() => {
    const controller = new AbortController();
    // The list restarts when its filters change.
    fetchPage(0, controller.signal);
    return () => controller.abort();
  }, [fetchPage]);

  const more = useCallback(() => fetchPage(loaded.current), [fetchPage]);
  return { ...state, loadMore: more };
}
