import { Badge, Button, Switch, Text } from '@fluentui/react-components';
import { ArrowUp16Regular } from '@fluentui/react-icons';
import { DataTable } from '../components/DataTable.jsx';

const STATUS = {
  loaded: { label: 'Running', color: 'success' },
  disabled: { label: 'Off', color: 'subtle' },
  failed: { label: 'Failed', color: 'danger' },
  incompatible: { label: 'Incompatible', color: 'warning' },
};

function Status({ addon }) {
  const shown = STATUS[addon.status] ?? { label: addon.status, color: 'informative' };
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      {addon.switched_off ? (
        <Badge appearance="tint" color="danger" title={addon.message ?? undefined}>
          Switched off by VethuQ
        </Badge>
      ) : (
        <Badge appearance="tint" color={shown.color} title={addon.detail || undefined}>
          {shown.label}
        </Badge>
      )}
      {addon.restart && (
        <Badge appearance="outline" color="informative">
          {addon.disabled ? 'Turns off at restart' : 'Turns on at restart'}
        </Badge>
      )}
    </span>
  );
}

/**
 * The add-ons that are installed: whether each runs, whether a newer version is announced, and a
 * switch to turn it off (applied at the next start).
 */
export function InstalledTab({ addons, busy, onToggle, onUpdate }) {
  const columns = [
    {
      key: 'name',
      label: 'Add-on',
      render: (a) => (
        <span>
          <Text block>{a.name}</Text>
          <Text size={200} style={{ opacity: 0.7 }}>
            {a.id}
            {a.detail && a.status !== 'disabled' ? ` · ${a.detail}` : ''}
            {a.message ? ` · ${a.message}` : ''}
          </Text>
        </span>
      ),
    },
    { key: 'version', label: 'Version', render: (a) => a.version || '—' },
    { key: 'status', label: 'Status', render: (a) => <Status addon={a} /> },
    {
      key: 'update',
      label: 'Update',
      render: (a) =>
        a.update ? (
          <Button
            size="small"
            icon={<ArrowUp16Regular />}
            disabled={busy}
            onClick={() => onUpdate(a)}
            aria-label={`Update ${a.id} to ${a.latest}`}
          >
            {a.latest}
          </Button>
        ) : a.latest ? (
          'Up to date'
        ) : (
          '—'
        ),
    },
    { key: 'licence', label: 'Licence', render: (a) => (a.licence ? 'Entered' : '—') },
    {
      key: 'on',
      label: 'On',
      render: (a) => (
        <Switch
          aria-label={`Turn ${a.id} on or off`}
          checked={!a.disabled}
          disabled={a.switched_off || a.id === 'english'}
          onChange={(_, data) => onToggle(a, data.checked)}
        />
      ),
    },
  ];
  return (
    <DataTable label="Installed add-ons" columns={columns} rows={addons} rowKey={(a) => a.id} />
  );
}
