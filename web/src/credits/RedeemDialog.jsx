import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  MessageBar,
  MessageBarBody,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import { useState } from 'react';
import { api } from '../api/client.js';
import { formatCredits } from '../format.js';

/** Paste a licence; its credit grants are added, each once. */
function RedeemBody({ onClose, onRedeemed }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const { redeemed } = await api.credits.redeem(token);
      setResult(redeemed);
      onRedeemed(redeemed);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBody>
      <DialogTitle>Redeem a licence</DialogTitle>
      <DialogContent>
        {result ? (
          <MessageBar intent={result.some((r) => r.added) ? 'success' : 'info'}>
            <MessageBarBody>
              {result.length === 0
                ? 'This licence has no credits.'
                : result
                    .map((r) =>
                      r.added
                        ? `Added ${formatCredits(r.credits)} credits (${r.id}).`
                        : `Already redeemed (${r.id}).`,
                    )
                    .join(' ')}
            </MessageBarBody>
          </MessageBar>
        ) : (
          <Field
            label="Licence"
            validationMessage={error}
            validationState={error ? 'error' : 'none'}
          >
            <Textarea
              rows={5}
              value={token}
              onChange={(_, data) => setToken(data.value)}
              placeholder="Paste the licence text"
            />
          </Field>
        )}
      </DialogContent>
      <DialogActions>
        <Button appearance="secondary" onClick={onClose}>
          {result ? 'Close' : 'Cancel'}
        </Button>
        {!result && (
          <Button appearance="primary" disabled={!token.trim() || busy} onClick={submit}>
            {busy ? <Spinner size="tiny" /> : 'Redeem'}
          </Button>
        )}
      </DialogActions>
    </DialogBody>
  );
}

export function RedeemDialog({ open, onClose, onRedeemed }) {
  return (
    <Dialog open={open} onOpenChange={(_, data) => !data.open && onClose()}>
      <DialogSurface>
        {open && <RedeemBody onClose={onClose} onRedeemed={onRedeemed} />}
      </DialogSurface>
    </Dialog>
  );
}
