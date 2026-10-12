import { useCallback, useState } from 'react';
import { api } from '../api/client.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { useSourceActions } from './useSourceActions.js';

/** Adding a folder or a file: the host's picker where there is one, else a typed path. */
export function useAdd() {
  const platform = usePlatform();
  const actions = useSourceActions();
  const [typing, setTyping] = useState(/** @type {'folder' | 'file' | null} */ (null));

  const pick = useCallback(
    async (kind) => {
      const picker = kind === 'folder' ? platform.folderDialog : platform.fileDialog;
      if (!picker) {
        setTyping(kind);
        return null;
      }
      const { path } = await (kind === 'folder' ? api.dialog.folder() : api.dialog.file());
      return path ? actions.add(path) : null;
    },
    [platform, actions],
  );

  const typed = useCallback(
    async (path) => {
      const added = await actions.add(path);
      if (added) setTyping(null);
      return added;
    },
    [actions],
  );

  return { pick, typing, typed, closeTyping: () => setTyping(null) };
}
