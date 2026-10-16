import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Link,
  Spinner,
  Text,
} from '@fluentui/react-components';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useTask } from '../maintenance/useTask.js';

/**
 * Tells the person a newer VethuQ exists, and offers three things: Install now, Later (hide the
 * notice for a day) and Skip this version. It looks at what is already saved (no request is made
 * to the internet), appears at most once a visit, and never when the check is off, the version
 * was skipped or the notice is snoozed. A version below the minimum is explained but cannot be
 * put off, because it only says why some features are held back; nothing local is ever blocked.
 *
 * Install now is offered only to the installed (desktop) build. Everyone else sees the exact
 * commands: VethuQ does not upgrade itself in place.
 */
export function UpdateDialog() {
  const [update, setUpdate] = useState(null);
  const [help, setHelp] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [installing, setInstalling] = useState(false);
  const { task, start } = useTask('update-install', (done) => {
    if (done.error) {
      setInstalling(false);
      setError(done.error);
    }
  });

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const status = await api.maintenance.updates(controller.signal);
        if (!status?.notify || !status.latest) return;
        const steps = await api.maintenance.updatesHelp(controller.signal).catch(() => null);
        setUpdate(status);
        setHelp(steps);
        setOpen(true);
      } catch {
        // Nothing saved or the service is not answering: say nothing.
      }
    })();
    return () => controller.abort();
  }, []);

  const run = useCallback(async (call, then) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      then?.();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }, []);

  if (!update) return null;
  const required = update.status === 'below_minimum';
  const canInstall = help?.install_type === 'installer' && update.offer_install;
  const working = installing || task.running;

  const install = () =>
    run(
      () => start(api.maintenance.updatesInstall),
      () => setInstalling(true),
    );

  return (
    <Dialog
      open={open}
      modalType="alert"
      onOpenChange={(_, data) => !data.open && !working && !required && setOpen(false)}
    >
      <DialogSurface aria-label="Update available">
        <DialogBody>
          <DialogTitle>
            {required ? 'Please update VethuQ' : `VethuQ ${update.latest} is available`}
          </DialogTitle>
          <DialogContent>
            <Text block>{update.message}</Text>
            {update.release_notes_url && (
              <Link href={update.release_notes_url} target="_blank" rel="noreferrer">
                Release notes
              </Link>
            )}
            {working && (
              <Text block>
                <Spinner size="tiny" /> Installing the update. VethuQ will close and open again; any
                indexing that was waiting carries on afterwards. Windows may ask for permission to
                restart the background service.
              </Text>
            )}
            {!canInstall && help?.commands?.length > 0 && (
              <>
                <Text block>To update, run:</Text>
                {help.commands.map((command) => (
                  <Text block key={command} font="monospace">
                    {command}
                  </Text>
                ))}
              </>
            )}
            {error && (
              <Text block role="alert">
                {error}
              </Text>
            )}
          </DialogContent>
          <DialogActions>
            {!required && (
              <Button
                appearance="subtle"
                disabled={busy || working}
                onClick={() =>
                  run(
                    () => api.maintenance.updatesSkip(),
                    () => setOpen(false),
                  )
                }
              >
                Skip this version
              </Button>
            )}
            {!required && (
              <Button
                appearance="secondary"
                disabled={busy || working}
                onClick={() =>
                  run(
                    () => api.maintenance.updatesLater(1),
                    () => setOpen(false),
                  )
                }
              >
                Later
              </Button>
            )}
            {required && !canInstall && (
              <Button appearance="secondary" onClick={() => setOpen(false)}>
                Close
              </Button>
            )}
            {canInstall && (
              <Button appearance="primary" disabled={busy || working} onClick={install}>
                Install now
              </Button>
            )}
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
