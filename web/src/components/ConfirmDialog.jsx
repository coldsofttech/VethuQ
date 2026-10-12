import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Spinner,
} from '@fluentui/react-components';

/**
 * A question with two answers. Escape and the cancel button leave things as they are.
 *
 * @param {{ open: boolean, title: string, children?: import('react').ReactNode,
 *   confirmLabel: string, cancelLabel?: string, busy?: boolean,
 *   onConfirm: () => void, onCancel: () => void }} props
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  busy = false,
  onConfirm,
  onCancel,
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(_, data) => {
        if (!data.open && data.type === 'escapeKeyDown' && !busy) onCancel();
      }}
    >
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent>{children}</DialogContent>
          <DialogActions>
            <Button appearance="secondary" disabled={busy} onClick={onCancel}>
              {cancelLabel}
            </Button>
            <Button appearance="primary" disabled={busy} onClick={onConfirm}>
              {busy ? <Spinner size="tiny" /> : confirmLabel}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
