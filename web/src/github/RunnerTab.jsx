import {
  Badge,
  Button,
  Checkbox,
  Field,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { api } from '../api/client.js';
import { ConfirmDialog } from '../components/ConfirmDialog.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { GroupHeading } from '../components/GroupHeading.jsx';
import { useNotify } from '../components/Notifications.jsx';
import { formatDate } from '../format.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    maxWidth: '520px',
  },
  row: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  facts: {
    display: 'grid',
    gridTemplateColumns: 'max-content 1fr',
    gap: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalXL}`,
  },
  muted: { color: tokens.colorNeutralForeground3 },
});

function Facts({ rows }) {
  const styles = useStyles();
  return (
    <div className={styles.facts}>
      {rows.map(([label, value]) => (
        <span key={label} style={{ display: 'contents' }}>
          <Text className={styles.muted}>{label}</Text>
          <Text>{value}</Text>
        </span>
      ))}
    </div>
  );
}

function SetupForm({ versions, token, storeAvailable, onDone }) {
  const styles = useStyles();
  const notify = useNotify();
  const [repo, setRepo] = useState('vethuq-runner');
  const [owner, setOwner] = useState('');
  const [isPrivate, setPrivate] = useState(true);
  const [ref, setRef] = useState('');
  const [existing, setExisting] = useState(false);
  const [save, setSave] = useState(false);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.github.setup({
        repo,
        owner,
        private: isPrivate,
        token: token.value,
        workflow_ref: ref,
        create: !existing,
        adopt: existing,
        master_key: key,
        store: save,
      });
      token.set('');
      notify({ title: 'The GitHub runner is set up' });
      onDone();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  const options = [
    { value: '', label: 'Newest' },
    ...versions.map((v) => ({ value: v.workflow_ref, label: `${v.workflow_ref} (${v.status})` })),
  ];
  return (
    <div className={styles.form}>
      <GroupHeading
        title="Set up the runner"
        note="VethuQ makes a repository in your GitHub account, adds its workflow and a key. Pages that need OCR are encrypted and read there. Pages with a text layer never leave this computer."
      />
      <Field label="Repository name">
        <Input value={repo} onChange={(_, d) => setRepo(d.value)} />
      </Field>
      <Field label="Owner" hint="Your user or an organisation. Left empty it is the token's user.">
        <Input value={owner} onChange={(_, d) => setOwner(d.value)} />
      </Field>
      <Checkbox
        label="Private repository (recommended: public ones show job sizes and timing)"
        checked={isPrivate}
        onChange={(_, d) => setPrivate(d.checked === true)}
      />
      <Checkbox
        label="The repository already exists: use it"
        checked={existing}
        onChange={(_, d) => setExisting(d.checked === true)}
      />
      {storeAvailable && (
        <Checkbox
          label="Save the token in Windows Credential Manager"
          checked={save}
          onChange={(_, d) => setSave(d.checked === true)}
        />
      )}
      <Field label="Runner version">
        <FilterSelect label="Runner version" value={ref} options={options} onChange={setRef} />
      </Field>
      <Field
        label="Master key (only to restore one)"
        hint="Left empty, the key on this computer is reused, or a new one is made."
      >
        <Input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(_, d) => setKey(d.value)}
        />
      </Field>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}
      <div className={styles.row}>
        <Button appearance="primary" disabled={busy || !repo.trim()} onClick={submit}>
          {busy ? <Spinner size="tiny" /> : 'Set up'}
        </Button>
        <Text className={styles.muted}>
          Unless you save it, the token above is used once and not kept.
        </Text>
      </div>
    </div>
  );
}

function RunnerCard({ data, token, onChanged }) {
  const styles = useStyles();
  const notify = useNotify();
  const runner = data.runner;
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [ref, setRef] = useState('');
  const [removing, setRemoving] = useState(false);
  const [deleteRepo, setDeleteRepo] = useState(false);
  const [deleteKey, setDeleteKey] = useState(false);

  const run = async (name, call, success) => {
    setBusy(name);
    setError(null);
    try {
      const result = await call();
      if (success) notify({ title: success });
      return result;
    } catch (failure) {
      setError(failure.message);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const check = async () => {
    const result = await run('check', () => api.github.status(token.value));
    if (result) setStatus(result);
  };
  const update = async () => {
    const done = await run(
      'update',
      () => api.github.update({ token: token.value, workflow_ref: ref }),
      'The runner is updated',
    );
    if (done) {
      setStatus(null);
      onChanged();
    }
  };
  const remove = async () => {
    setRemoving(false);
    const done = await run(
      'remove',
      () =>
        api.github.remove({ token: token.value, delete_repo: deleteRepo, delete_key: deleteKey }),
      'The runner is removed',
    );
    if (done) onChanged();
  };

  const options = [
    { value: '', label: 'Newest' },
    ...data.versions.map((v) => ({
      value: v.workflow_ref,
      label: `${v.workflow_ref} (${v.status})`,
    })),
  ];
  return (
    <div className={styles.root}>
      <GroupHeading title="Runner" note="The repository on GitHub that reads your pages." />
      <Facts
        rows={[
          [
            'Repository',
            <Link href={runner.url} target="_blank" rel="noreferrer" key="r">
              {runner.owner}/{runner.repo}
            </Link>,
          ],
          ['Visibility', runner.private ? 'Private' : 'Public'],
          ['Version', runner.workflow_ref],
          ['Image', runner.image],
          ['Protocol', runner.protocol],
          ['Key fingerprint', runner.key_fingerprint],
          ['Set up', formatDate(runner.set_up_at)],
          ...(data.tier
            ? [['Tier', data.tier.available ? 'Ready to use' : data.tier.reason || 'Unavailable']]
            : []),
        ]}
      />
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}
      {status && (
        <MessageBar intent={status.ok ? 'success' : 'warning'}>
          <MessageBarBody>
            {status.ok ? 'The runner is in good order.' : 'The runner needs attention.'}
            {status.up_to_date === false && <div>A newer runner version is available.</div>}
            {status.problems.map((p) => (
              <div key={p}>{p}</div>
            ))}
            <div className={styles.row}>
              <Badge appearance="tint" color={status.repo_found ? 'success' : 'danger'}>
                {status.repo_found ? 'Repository found' : 'Repository missing'}
              </Badge>
              <Badge appearance="tint" color={status.secret_set ? 'success' : 'danger'}>
                {status.secret_set ? 'Key secret set' : 'Key secret missing'}
              </Badge>
              <Badge appearance="tint" color={status.caller_ok ? 'success' : 'danger'}>
                {status.caller_ok ? 'Workflow unchanged' : 'Workflow changed'}
              </Badge>
            </div>
          </MessageBarBody>
        </MessageBar>
      )}
      <div className={styles.row}>
        <Button disabled={busy !== null} onClick={check}>
          {busy === 'check' ? <Spinner size="tiny" /> : 'Check on GitHub'}
        </Button>
        <FilterSelect label="Update to" value={ref} options={options} onChange={setRef} />
        <Button disabled={busy !== null} onClick={update}>
          {busy === 'update' ? <Spinner size="tiny" /> : 'Update the runner'}
        </Button>
        <Button disabled={busy !== null} onClick={() => setRemoving(true)}>
          Remove…
        </Button>
      </div>
      <ConfirmDialog
        open={removing}
        title="Remove the runner?"
        confirmLabel="Remove"
        onConfirm={remove}
        onCancel={() => setRemoving(false)}
      >
        VethuQ forgets the runner. Jobs already sent can no longer be read without the key.
        <Checkbox
          label="Also delete the repository on GitHub"
          checked={deleteRepo}
          onChange={(_, d) => setDeleteRepo(d.checked === true)}
        />
        <Checkbox
          label="Also delete the master key from this computer"
          checked={deleteKey}
          onChange={(_, d) => setDeleteKey(d.checked === true)}
        />
      </ConfirmDialog>
    </div>
  );
}

/** The runner repository: set it up, look at it, update or remove it. */
export function RunnerTab({ data, token, onChanged }) {
  return data.runner ? (
    <RunnerCard data={data} token={token} onChanged={onChanged} />
  ) : (
    <SetupForm
      versions={data.versions}
      token={token}
      storeAvailable={data.token.store_available}
      onDone={onChanged}
    />
  );
}
