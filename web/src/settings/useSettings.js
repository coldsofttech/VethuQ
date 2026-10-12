import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';

/**
 * The settings of one section, with saving. A change shows at once and is undone, with the
 * reason, if the service refuses it.
 *
 * @param {string} section
 */
export function useSettings(section) {
  const [state, setState] = useState({
    settings: /** @type {import('../api/client.js').Setting[]} */ ([]),
    loading: true,
    error: null,
  });
  const [busy, setBusy] = useState(/** @type {Record<string, boolean>} */ ({}));
  const [problems, setProblems] = useState(/** @type {Record<string, string>} */ ({}));

  useEffect(() => {
    const controller = new AbortController();
    api.settings.list(section, controller.signal).then(
      (result) => setState({ settings: result.settings, loading: false, error: null }),
      (error) => {
        if (error?.name !== 'AbortError') setState({ settings: [], loading: false, error });
      },
    );
    return () => controller.abort();
  }, [section]);

  const replace = useCallback(
    (updated) =>
      setState((current) => ({
        ...current,
        settings: current.settings.map((item) => (item.id === updated.id ? updated : item)),
      })),
    [],
  );

  const run = useCallback(
    async (id, optimistic, call) => {
      setProblems((current) => ({ ...current, [id]: '' }));
      setBusy((current) => ({ ...current, [id]: true }));
      let previous;
      setState((current) => {
        previous = current.settings.find((item) => item.id === id);
        return optimistic
          ? {
              ...current,
              settings: current.settings.map((item) =>
                item.id === id ? { ...item, ...optimistic } : item,
              ),
            }
          : current;
      });
      try {
        replace(await call());
      } catch (error) {
        if (previous) replace(previous);
        setProblems((current) => ({ ...current, [id]: error.message || 'Could not save.' }));
      } finally {
        setBusy((current) => ({ ...current, [id]: false }));
      }
    },
    [replace],
  );

  const update = useCallback(
    (id, value) =>
      run(id, { value, is_default: false }, () => api.settings.update(section, id, value)),
    [run, section],
  );
  const reset = useCallback(
    (id) => run(id, null, () => api.settings.reset(section, id)),
    [run, section],
  );

  return { ...state, busy, problems, update, reset };
}
