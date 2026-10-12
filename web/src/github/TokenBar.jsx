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
 * The GitHub token. It is used for the call and never stored by VethuQ; "Use for this session" keeps it in
 * the memory of this application, where indexing on GitHub reads it, until you close the application.
 */
export function TokenBar({ token, state, onState }) {
  const styles = useStyles();
  const notify = useNotify();
  const [busy, setBusy] = useState(false);

  const keep = async (value) => {
    setBusy(true);
    try {
      onState(await api.github.token(value));
      if (value) token.set('');
      notify({ title: value ? 'The token is kept for this session' : 'The token is forgotten' });
    } catch (failure) {
      notify({ title: 'Could not do that', body: failure.message, intent: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const where = state.session
    ? 'A token is kept for this session.'
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
      <Button disabled={busy || !token.value} onClick={() => keep(token.value)}>
        Use for this session
      </Button>
      <Button disabled={busy || !state.session} onClick={() => keep(null)}>
        Forget
      </Button>
      <Text size={200} className={styles.muted}>
        VethuQ never writes the token to disk.
      </Text>
    </div>
  );
}
