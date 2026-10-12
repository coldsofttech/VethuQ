import {
  Badge,
  Body1,
  Tab,
  TabList,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { strings } from '../strings.js';

const text = strings.about;

function availability(item) {
  const ok = item.available;
  return (
    <Badge appearance="tint" color={ok ? 'success' : 'danger'} title={item.reason || undefined}>
      {ok ? text.available : text.unavailable}
    </Badge>
  );
}

const dim = (value) => (value ? value : '—');

// One table per tab: which rows to show and how each column renders.
const SECTIONS = {
  add_ons: [
    { key: 'name', header: text.columns.name, cell: (row) => row.name },
    { key: 'version', header: text.columns.version, cell: (row) => row.version },
    {
      key: 'status',
      header: text.columns.status,
      cell: (row) => (
        <Badge
          appearance="tint"
          color={row.status === 'loaded' ? 'success' : 'warning'}
          title={row.detail || undefined}
        >
          {row.status}
        </Badge>
      ),
    },
  ],
  file_types: [
    { key: 'label', header: text.columns.label, cell: (row) => row.label },
    { key: 'extensions', header: text.columns.extensions, cell: (row) => row.extensions.join(' ') },
    { key: 'state', header: text.columns.state, cell: availability },
  ],
  search_engines: [
    { key: 'label', header: text.columns.label, cell: (row) => row.label },
    { key: 'description', header: text.columns.description, cell: (row) => dim(row.description) },
    { key: 'state', header: text.columns.state, cell: availability },
  ],
  languages: [
    { key: 'label', header: text.columns.label, cell: (row) => row.label },
    {
      key: 'native_label',
      header: text.columns.native_label,
      cell: (row) => dim(row.native_label),
    },
    {
      key: 'state',
      header: text.columns.state,
      cell: (row) =>
        row.available ? (
          <Badge appearance="tint" color={row.enabled ? 'success' : 'informative'}>
            {row.enabled ? text.enabled : text.disabled}
          </Badge>
        ) : (
          availability(row)
        ),
    },
  ],
  ocr_engines: [
    { key: 'label', header: text.columns.label, cell: (row) => row.label },
    { key: 'profiles', header: text.columns.profiles, cell: (row) => row.profiles.join(', ') },
    { key: 'state', header: text.columns.state, cell: availability },
  ],
};

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  table: { maxWidth: '820px' },
  empty: { color: tokens.colorNeutralForeground3 },
});

/** @param {{ catalog: import('../api/client.js').Catalog }} props */
export function CatalogTabs({ catalog }) {
  const styles = useStyles();
  const [selected, setSelected] = useState('add_ons');
  const rows = catalog[selected] ?? [];
  const columns = SECTIONS[selected];

  return (
    <div className={styles.root}>
      <TabList selectedValue={selected} onTabSelect={(_, data) => setSelected(String(data.value))}>
        {Object.keys(SECTIONS).map((key) => (
          <Tab key={key} value={key}>
            {text.tabs[key]} ({(catalog[key] ?? []).length})
          </Tab>
        ))}
      </TabList>
      {rows.length === 0 ? (
        <Body1 className={styles.empty}>{text.empty}</Body1>
      ) : (
        <Table className={styles.table} aria-label={text.tabs[selected]} size="small">
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHeaderCell key={column.key}>
                  <Text weight="semibold">{column.header}</Text>
                </TableHeaderCell>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                {columns.map((column) => (
                  <TableCell key={column.key}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
