import { Badge, Button, MessageBar, MessageBarBody } from '@fluentui/react-components';
import { ArrowDownload16Regular } from '@fluentui/react-icons';
import { DataTable } from '../components/DataTable.jsx';

/** The optional packs VethuQ names, and a button to install each that is not installed yet. */
export function PacksTab({ packs, install, busy, onInstall }) {
  const columns = [
    { key: 'id', label: 'Pack' },
    { key: 'note', label: 'What it adds' },
    {
      key: 'packages',
      label: 'Packages',
      render: (p) =>
        p.packages.map((x) => (x.version ? `${x.name} ${x.version}` : x.name)).join(', '),
    },
    {
      key: 'installed',
      label: 'Status',
      render: (p) => (
        <Badge appearance="tint" color={p.installed ? 'success' : 'informative'}>
          {p.installed ? 'Installed' : 'Not installed'}
        </Badge>
      ),
    },
    {
      key: 'action',
      label: '',
      render: (p) =>
        p.installed ? null : (
          <Button
            size="small"
            icon={<ArrowDownload16Regular />}
            disabled={busy || !install.ok}
            onClick={() => onInstall(p)}
            aria-label={`Install ${p.id}`}
          >
            Install
          </Button>
        ),
    },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {!install.ok && (
        <MessageBar intent="warning">
          <MessageBarBody>{install.reason}</MessageBarBody>
        </MessageBar>
      )}
      <DataTable label="Add-on packs" columns={columns} rows={packs} rowKey={(p) => p.id} />
    </div>
  );
}
