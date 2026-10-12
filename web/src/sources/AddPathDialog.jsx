import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
} from '@fluentui/react-components';
import { useState } from 'react';

/**
 * Where there is no file picker (a browser), the path is typed.
 * @param {{ kind: 'folder' | 'file' | null, onAdd: (path: string) => void, onClose: () => void }} props
 */
export function AddPathDialog({ kind, onAdd, onClose }) {
  const [path, setPath] = useState('');
  return (
    <Dialog open={kind !== null} onOpenChange={(_, data) => !data.open && onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Add a {kind}</DialogTitle>
          <DialogContent>
            <Field label={`Path of the ${kind}`}>
              <Input value={path} onChange={(_, data) => setPath(data.value)} />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              appearance="primary"
              disabled={!path.trim()}
              onClick={() => {
                onAdd(path.trim());
                setPath('');
              }}
            >
              Add
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
