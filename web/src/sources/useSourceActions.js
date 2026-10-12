import { useMemo } from 'react';
import { api } from '../api/client.js';
import { useNotify } from '../components/Notifications.jsx';
import { useIndexing } from '../indexing/IndexingProvider.jsx';

/**
 * Changes to sources, each with its toast: success says what happened, failure says why. They
 * answer with the result, or null when it failed.
 */
export function useSourceActions() {
  const notify = useNotify();
  const { bump } = useIndexing();

  return useMemo(() => {
    const attempt = async (call, success, failure) => {
      try {
        const result = await call();
        if (success) notify({ title: success(result) });
        bump();
        return result;
      } catch (error) {
        notify({ title: failure, body: error.message, intent: 'error' });
        return null;
      }
    };
    return {
      add: (path) =>
        attempt(
          () => api.sources.add(path),
          (s) => `Added ${s.name}`,
          'Could not add the source',
        ),
      remove: (source) =>
        attempt(
          () => api.sources.remove(source.id),
          () => `Removed ${source.name}`,
          'Could not remove the source',
        ),
      restore: (source) =>
        attempt(
          () => api.sources.restore(source.id),
          () => `Restored ${source.name}`,
          'Could not restore the source',
        ),
      purge: (source) =>
        attempt(
          () => api.sources.purge(source.id),
          () => `Deleted ${source.name}`,
          'Could not delete the source',
        ),
      setLanguages: (source, languages) =>
        attempt(
          () => api.sources.setLanguages(source.id, languages),
          () => `Languages of ${source.name} saved`,
          'Could not save the languages',
        ),
    };
  }, [notify, bump]);
}
