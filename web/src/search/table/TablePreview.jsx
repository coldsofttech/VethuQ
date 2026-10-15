import {
  Input,
  MessageBar,
  MessageBarBody,
  Select,
  Spinner,
  Switch,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Dismiss16Regular, Search16Regular } from '@fluentui/react-icons';
import { TableViewer } from '@vethuq/table-viewer';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client.js';
import { ToolButton } from '../../components/ToolButton.jsx';
import { PreviewFrame } from '../PreviewFrame.jsx';

const useStyles = makeStyles({
  body: { flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
  bar: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  filter: { flexGrow: 1, minWidth: '120px' },
  muted: { color: tokens.colorNeutralForeground3, whiteSpace: 'nowrap' },
  viewer: { flexGrow: 1, minHeight: 0 },
  centered: { margin: 'auto', padding: tokens.spacingVerticalL },
});

const FILTER_DELAY = 250;

/** The route that reads each file type as rows (CSV when the type is not listed). */
const WINDOWS = {
  csv: api.files.csvWindow,
  tsv: api.files.tsvWindow,
  parquet: api.files.parquetWindow,
};

/**
 * A CSV, TSV or Parquet file of the results as a table beside them, read from disk: sort by a column, filter the
 * rows (in every column or one), resize columns, and say whether the first row is a header (it is
 * guessed). Opens on the matching row with the matching cell marked.
 *
 * @param {object} props
 * @param {Array<object>} props.matches The loaded matches in this file, in order.
 * @param {number} props.index The one shown.
 * @param {(index: number) => void} props.onIndex
 * @param {() => void} props.onClose
 */
export default function TablePreview({ matches, index, onIndex, onClose }) {
  const styles = useStyles();
  const match = matches[index];
  const path = match.file_path;
  const rowsOf = WINDOWS[match.file_type] ?? api.files.csvWindow;
  const [sort, setSort] = useState(null);
  const [typed, setTyped] = useState('');
  const [filter, setFilter] = useState('');
  const [column, setColumn] = useState('');
  const [headerChoice, setHeaderChoice] = useState(null);
  const [probe, setProbe] = useState({ key: null, info: null, error: null });
  const [widths, setWidths] = useState({ path: null, value: null });

  useEffect(() => {
    const timer = setTimeout(() => setFilter(typed.trim()), FILTER_DELAY);
    return () => clearTimeout(timer);
  }, [typed]);

  const params = useMemo(
    () => ({
      path,
      sort: sort?.column,
      dir: sort?.descending ? 'desc' : undefined,
      filter: filter || undefined,
      column: column === '' ? undefined : Number(column),
      header: headerChoice === null ? undefined : headerChoice ? 1 : 0,
    }),
    [path, sort, filter, column, headerChoice],
  );
  const key = JSON.stringify([params, match.line, match.column]);

  // One small request tells how many rows the view has, the header, and where the match is.
  useEffect(() => {
    const controller = new AbortController();
    rowsOf(
      { ...params, start: 0, count: 1, at_row: match.line, at_offset: match.column },
      controller.signal,
    ).then(
      (info) => {
        setProbe({ key, info, error: null });
        setWidths((w) => (w.path === path ? w : { path, value: info.widths }));
      },
      (error) => error?.name !== 'AbortError' && setProbe({ key, info: null, error }),
    );
    return () => controller.abort();
  }, [rowsOf, params, key, match.line, match.column, path]);

  const loadRows = useCallback(
    (start, count) => rowsOf({ ...params, start, count }),
    [rowsOf, params],
  );

  const info = probe.info;
  const target = useMemo(() => {
    const t = info?.target;
    if (!t || t.index == null) return undefined;
    return { index: t.index, column: t.column, text: match.matched };
  }, [info, match.matched]);

  const headerOn = headerChoice ?? info?.header_detected ?? false;
  const names = info?.header ?? [];
  const shown = info?.total ?? 0;
  const ready = widths.path === path && info !== null;

  return (
    <PreviewFrame
      label="Table preview"
      match={match}
      index={index}
      count={matches.length}
      place={match.line ? `row ${match.line}` : 'table'}
      onIndex={onIndex}
      onClose={onClose}
    >
      <div className={styles.body}>
        <div className={styles.bar}>
          <Input
            className={styles.filter}
            size="small"
            value={typed}
            placeholder="Filter rows"
            aria-label="Filter rows"
            contentBefore={<Search16Regular />}
            contentAfter={
              typed ? (
                <ToolButton
                  label="Clear the filter"
                  icon={<Dismiss16Regular />}
                  appearance="transparent"
                  size="small"
                  onClick={() => setTyped('')}
                />
              ) : undefined
            }
            onChange={(_, data) => setTyped(data.value)}
          />
          <Select
            size="small"
            aria-label="Filter column"
            value={column}
            onChange={(_, data) => setColumn(data.value)}
          >
            <option value="">All columns</option>
            {Array.from({ length: info?.columns ?? 0 }, (_, c) => (
              <option key={c} value={String(c)}>
                {names[c] || `Column ${c + 1}`}
              </option>
            ))}
          </Select>
          <Switch
            label="First row is header"
            checked={headerOn}
            onChange={(_, data) => setHeaderChoice(data.checked)}
          />
          {info && (
            <Text className={styles.muted}>
              {shown === info.all
                ? `${info.all.toLocaleString()} rows`
                : `${shown.toLocaleString()} of ${info.all.toLocaleString()} rows`}
            </Text>
          )}
        </div>
        {probe.error && (
          <MessageBar intent="error">
            <MessageBarBody>The table could not be shown: {probe.error.message}</MessageBarBody>
          </MessageBar>
        )}
        {info?.truncated && (
          <MessageBar intent="info">
            <MessageBarBody>
              This table is very large: the first {info.all.toLocaleString()} rows are shown, which
              are the rows VethuQ indexed.
            </MessageBarBody>
          </MessageBar>
        )}
        {!ready && !probe.error && (
          <Spinner className={styles.centered} size="small" label="Opening" />
        )}
        {ready && (
          <div className={styles.viewer}>
            <TableViewer
              key={path}
              columns={info.columns}
              header={info.header}
              widths={widths.value}
              total={info.total}
              loadRows={loadRows}
              target={target}
              sort={sort}
              onSort={(c, descending) => setSort(c === null ? null : { column: c, descending })}
              label="Rows of the file"
            />
          </div>
        )}
      </div>
    </PreviewFrame>
  );
}
