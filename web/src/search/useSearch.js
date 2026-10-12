import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const PAGE = 50;
const IDLE = {
  items: [],
  total: 0,
  loading: false,
  error: null,
  done: false,
  engine: null,
  pending: {},
  indexRebuilt: false,
};

/**
 * Runs a search and pages through it: `run(request)` starts again from the first page, `more()` loads the
 * next. Matches come sorted, so those of one file sit together while scrolling.
 */
export function useSearch() {
  const [state, setState] = useState(IDLE);
  const request = useRef(null);
  const token = useRef(0);
  const controller = useRef(null);

  const fetchPage = useCallback(async (offset) => {
    const mine = ++token.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const page = await api.search.run(
        { ...request.current, limit: PAGE, offset },
        controller.current.signal,
      );
      if (mine !== token.current) return;
      setState((s) => ({
        items: offset === 0 ? page.matches : [...s.items, ...page.matches],
        total: page.total,
        loading: false,
        error: null,
        done: true,
        engine: page.engine,
        pending: page.pending ?? {},
        indexRebuilt: page.index_rebuilt === true,
      }));
    } catch (error) {
      if (error?.name !== 'AbortError' && mine === token.current)
        setState((s) => ({ ...s, loading: false, error, done: true }));
    }
  }, []);

  const run = useCallback(
    (body) => {
      request.current = body;
      return fetchPage(0);
    },
    [fetchPage],
  );

  const more = useCallback(() => {
    if (!request.current) return undefined;
    return fetchPage(state.items.length);
  }, [fetchPage, state.items.length]);

  useEffect(() => () => controller.current?.abort(), []);

  return {
    ...state,
    run,
    more,
    request: request.current,
    hasMore: state.items.length < state.total,
  };
}
