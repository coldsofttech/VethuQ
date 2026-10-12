import { Button, Field, Input, Text, makeStyles, tokens } from '@fluentui/react-components';
import { useState } from 'react';
import { api } from '../api/client.js';
import { useNotify } from '../components/Notifications.jsx';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: tokens.spacingHorizontalM,
    flexWrap: 'wrap',
    padding: tokens.spacingVerticalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
  },
  field: { minWidth: '280px', flexGrow: 1 },
  muted: { color: tokens.colorNeutralForeground3 },
});

/**
 * The GitHub token. It is used for the call and not kept by VethuQ unless you choose: "Save in Credential
 * Manager" hands it to Windows (so the background service and the command line find it too), and "Use
 * for this session" keeps it in this application's memory until you close it.
 */
export function TokenBar({ token, state, onState }) {
  const styles = useStyles();
  const notify = useNotify();
  const [busy, setBusy] = useState(false);

  const act = async (call, done) => {
    setBusy(true);
    try {
      onState(await call());
      notify({ title: done });
    } catch (failure) {
      notify({ title: 'Could not do that', body: failure.message, intent: 'error' });
    } finally {
      setBusy(false);
    }
  };
  const keep = async (store) => {
    await act(
      () => api.github.token(token.value, store),
      store
        ? 'The token is saved in Windows Credential Manager'
        : 'The token is kept for this session',
    );
    token.set('');
  };
  const forget = () => act(() => api.github.forgetToken(), 'The saved token is forgotten');

  const where = state.stored
    ? 'A token is saved in Windows Credential Manager.'
    : state.session
      ? 'A token is kept for this session only.'
      : state.environment
        ? 'A token is set in the environment.'
        : 'No token yet. Create a fine-grained token on GitHub and paste it here.';

  return (
    <div className={styles.root}>
      <Field className={styles.field} label="GitHub token" hint={where}>
        <Input
          type="password"
          autoComplete="off"
          value={token.value}
          onChange={(_, data) => token.set(data.value)}
          placeholder="github_pat_…"
        />
      </Field>
      {state.store_available && (
        <Button appearance="primary" disabled={busy || !token.value} onClick={() => keep(true)}>
          Save in Credential Manager
        </Button>
      )}
      <Button disabled={busy || !token.value} onClick={() => keep(false)}>
        Use for this session
      </Button>
      <Button disabled={busy || !(state.session || state.stored)} onClick={forget}>
        Forget
      </Button>
      <Text size={200} className={styles.muted}>
        VethuQ never writes the token to its own files. Saving it hands it to Windows, which keeps
        it encrypted for you.
      </Text>
    </div>
  );
}
