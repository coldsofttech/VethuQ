import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';

/**
 * What the host offers the interface. The desktop host reports window controls; the future web host
 * reports none, and the title bar and any other desktop-only part simply do not render.
 * @typedef {object} Platform
 * @property {'desktop' | 'web'} kind
 * @property {boolean} windowControls
 * @property {boolean} folderDialog  The host can show a folder picker.
 * @property {boolean} ready  False until the host has answered.
 */

/** @type {Platform} */
const UNKNOWN = { kind: 'web', windowControls: false, folderDialog: false, ready: false };

const PlatformContext = createContext(UNKNOWN);

export function PlatformProvider({ children }) {
  const [platform, setPlatform] = useState(UNKNOWN);

  useEffect(() => {
    const controller = new AbortController();
    api.platform(controller.signal).then(
      (info) =>
        setPlatform({
          kind: info.kind,
          windowControls: info.window_controls,
          folderDialog: info.folder_dialog === true,
          ready: true,
        }),
      (error) => {
        if (error?.name !== 'AbortError') setPlatform({ ...UNKNOWN, ready: true });
      },
    );
    return () => controller.abort();
  }, []);

  const value = useMemo(() => platform, [platform]);
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

/** @returns {Platform} */
export function usePlatform() {
  return useContext(PlatformContext);
}
