import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { ConfirmDialog } from './ConfirmDialog.jsx';

/**
 * Closing the window while a run that this application started is going would stop it. The host
 * holds the close back and tells us (`vethuq:close-blocked`); this asks, and on "yes" closes anyway,
 * stopping the run first.
 */
export function CloseGuard() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener('vethuq:close-blocked', show);
    return () => window.removeEventListener('vethuq:close-blocked', show);
  }, []);

  const closeAnyway = async () => {
    setBusy(true);
    try {
      await api.window.perform('close', { force: true });
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      title="Indexing is running"
      confirmLabel="Stop and close"
      cancelLabel="Keep open"
      busy={busy}
      onConfirm={closeAnyway}
      onCancel={() => setOpen(false)}
    >
      Indexing was started from this window, so it stops when VethuQ closes. It carries on from
      where it was the next time you index. To let it finish while the window is closed, install the
      background service.
    </ConfirmDialog>
  );
}
