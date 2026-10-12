import { useEffect, useState } from 'react';

/**
 * Runs an API call once and tracks its state.
 * @template T
 * @param {(signal: AbortSignal) => Promise<T>} load  Must be stable (defined outside the component).
 * @returns {{ data: T | null, error: Error | null, loading: boolean }}
 */
export function useApi(load) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => setState({ data, error: null, loading: false }),
      (error) => {
        if (error?.name !== 'AbortError') setState({ data: null, error, loading: false });
      },
    );
    return () => controller.abort();
  }, [load]);
  return state;
}
