import {
  Button,
  Card,
  Checkbox,
  Dropdown,
  Field,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Text,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { DataTable } from '../components/DataTable.jsx';
import { useNotify } from '../components/Notifications.jsx';

const useStyles = makeStyles({
  tab: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
  card: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  row: { display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
  muted: { color: tokens.colorNeutralForeground3 },
  privacy: { whiteSpace: 'pre-line' },
  code: { fontFamily: tokens.fontFamilyMonospace, overflowWrap: 'anywhere' },
});

const KINDS = [
  { value: 'new', label: 'A new licence' },
  { value: 'top-up', label: 'A top-up' },
  { value: 'rebind', label: 'Move to a new device (re-bind)' },
];

const STATUS_WORDS = {
  stored: 'Installed',
  replaced: 'Replaced the earlier licence',
  unchanged: 'Already installed',
  not_installed: 'Add-on not installed here',
};

const list = (value) => (value?.length ? value.join(', ') : '—');

function InstalledLicences({ rows, styles }) {
  if (rows.length === 0) return <Text className={styles.muted}>No licence is installed.</Text>;
  return (
    <DataTable
      label="Installed licences"
      rows={rows}
      rowKey={(row) => row.licence_id ?? row.installed_on.join('+')}
      columns={[
        { key: 'licence_id', label: 'Licence', render: (row) => row.licence_id ?? '—' },
        { key: 'status', label: 'Status', render: (row) => row.status },
        { key: 'valid_until', label: 'Valid until', render: (row) => row.valid_until ?? '—' },
        { key: 'lists', label: 'Unlocks', render: (row) => list(row.lists) },
        { key: 'installed_on', label: 'Installed on', render: (row) => list(row.installed_on) },
      ]}
    />
  );
}

function InstallPanel({ styles, onInstalled }) {
  const notify = useNotify();
  const chooser = useRef(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const choose = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > 16 * 1024) {
      setError('That file is too large to be a licence.');
      return;
    }
    setText((await file.text()).trim());
    setError(null);
  };

  const install = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const result = await api.licences.install(text.trim());
      setDone(result);
      setText('');
      notify({ title: `Installed on ${result.installed} add-on(s)` });
      onInstalled();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className={styles.card} aria-label="Install a licence">
      <Text weight="semibold">Install a licence</Text>
      <Text className={styles.muted}>
        Paste the key, or choose the .vqlic file you were sent. One licence unlocks every add-on it
        lists; each add-on still checks it itself.
      </Text>
      <Field label="Licence key">
        <Textarea
          value={text}
          onChange={(_, d) => setText(d.value)}
          resize="vertical"
          rows={3}
          spellCheck={false}
          autoComplete="off"
        />
      </Field>
      <div className={styles.row}>
        <Button appearance="primary" disabled={busy || !text.trim()} onClick={install}>
          Install
        </Button>
        <Button disabled={busy} onClick={() => chooser.current?.click()}>
          Choose a .vqlic file…
        </Button>
        <input
          ref={chooser}
          type="file"
          accept=".vqlic,.txt"
          hidden
          aria-label="Licence file"
          onChange={choose}
        />
        {busy && <Spinner size="tiny" />}
      </div>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}
      {done && (
        <DataTable
          label="Licence install result"
          rows={done.results}
          rowKey={(row) => row.addon_id}
          columns={[
            { key: 'addon_id', label: 'Add-on', render: (row) => row.addon_id },
            {
              key: 'status',
              label: 'Result',
              render: (row) => STATUS_WORDS[row.status] ?? row.status,
            },
          ]}
        />
      )}
    </Card>
  );
}

function RequestPanel({ styles }) {
  const notify = useNotify();
  const [kind, setKind] = useState('new');
  const [addons, setAddons] = useState('');
  const [bundle, setBundle] = useState('');
  const [wallet, setWallet] = useState('');
  const [note, setNote] = useState('');
  const [github, setGithub] = useState(false);
  const [runnerOwner, setRunnerOwner] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [made, setMade] = useState(null);

  const prepare = async () => {
    setBusy(true);
    setError(null);
    setMade(null);
    try {
      setMade(
        await api.licences.request({
          kind,
          addons: addons
            .split(/[\s,]+/)
            .map((item) => item.trim())
            .filter(Boolean),
          bundle: bundle.trim() || null,
          wallet: kind === 'top-up' ? wallet.trim() || null : null,
          note: note.trim() || null,
          github,
          runner_owner: runnerOwner.trim() || null,
        }),
      );
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(made.code);
      notify({ title: 'Request code copied' });
    } catch {
      notify({ title: 'Could not copy', body: 'Select the code and copy it.', intent: 'warning' });
    }
  };

  return (
    <Card className={styles.card} aria-label="Request a licence">
      <Text weight="semibold">Request a licence</Text>
      <Text className={styles.muted}>
        Prepare a request, check exactly what it contains, then open it as an issue on VethuQ&apos;s
        public GitHub page. Nothing is sent until you open it, and you need no GitHub sign-in to
        prepare it.
      </Text>
      <Field label="What for">
        <Dropdown
          value={KINDS.find((item) => item.value === kind)?.label}
          selectedOptions={[kind]}
          onOptionSelect={(_, d) => setKind(d.optionValue)}
        >
          {KINDS.map((item) => (
            <Option key={item.value} value={item.value}>
              {item.label}
            </Option>
          ))}
        </Dropdown>
      </Field>
      <Field label="Add-ons" hint="Ids separated by commas, for example docx, doc.">
        <Input value={addons} onChange={(_, d) => setAddons(d.value)} />
      </Field>
      <Field label="Bundle" hint="For example office.">
        <Input value={bundle} onChange={(_, d) => setBundle(d.value)} />
      </Field>
      {kind === 'top-up' && (
        <Field label="Wallet" hint="For example local.">
          <Input value={wallet} onChange={(_, d) => setWallet(d.value)} />
        </Field>
      )}
      <Field label="Note (optional)" hint="Public. Don't put contact details or keys here.">
        <Input maxLength={200} value={note} onChange={(_, d) => setNote(d.value)} />
      </Field>
      <Checkbox
        checked={github}
        onChange={(_, d) => setGithub(Boolean(d.checked))}
        label="Include my GitHub id (for a licence bound to my GitHub account)"
      />
      {github && (
        <Field
          label="Runner repository owner (optional)"
          hint="The GitHub user or organization that owns your runner repository."
        >
          <Input value={runnerOwner} onChange={(_, d) => setRunnerOwner(d.value)} />
        </Field>
      )}
      <div className={styles.row}>
        <Button appearance="primary" disabled={busy} onClick={prepare}>
          Prepare request
        </Button>
        {busy && <Spinner size="tiny" />}
      </div>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}
      {made && (
        <>
          <MessageBar intent="warning">
            <MessageBarBody className={styles.privacy}>{made.privacy}</MessageBarBody>
          </MessageBar>
          <DataTable
            label="What the issue will contain"
            rows={Object.entries(made.fields).map(([name, value]) => ({ name, value }))}
            rowKey={(row) => row.name}
            columns={[
              { key: 'name', label: 'Field', render: (row) => row.name.replace('_', ' ') },
              { key: 'value', label: 'Value', render: (row) => row.value },
            ]}
          />
          <Text className={styles.code}>{made.code}</Text>
          <div className={styles.row}>
            <Button onClick={copy}>Copy the request code</Button>
            <Link href={made.url} target="_blank" rel="noreferrer">
              Open the public issue
            </Link>
          </div>
        </>
      )}
    </Card>
  );
}

/**
 * Licences: what is installed, install one key for every add-on it lists, and prepare a request.
 * A request goes to a public page, so the screen says so and shows everything it will contain.
 */
export function LicencesTab({ onInstalled }) {
  const styles = useStyles();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.licences.list(controller.signal).then(
      (result) => {
        setRows(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [reload]);

  const installed = useCallback(() => {
    setReload((n) => n + 1);
    onInstalled?.();
  }, [onInstalled]);

  return (
    <div className={styles.tab}>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error.message}</MessageBarBody>
        </MessageBar>
      )}
      {!rows && !error && <Spinner size="small" label="Loading licences" />}
      {rows && <InstalledLicences rows={rows} styles={styles} />}
      <InstallPanel styles={styles} onInstalled={installed} />
      <RequestPanel styles={styles} />
    </div>
  );
}
