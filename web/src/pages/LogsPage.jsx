import {
  Badge,
  Button,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  Switch,
  Text,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowSync20Regular,
  Dismiss20Regular,
  Play20Regular,
  Pause20Regular,
  Search20Regular,
} from '@fluentui/react-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { PageHeader } from '../components/PageHeader.jsx';
import { ToolButton } from '../components/ToolButton.jsx';
import { download, formatBytes } from '../format.js';
import { useLogEntries } from '../logs/useLogEntries.js';

const useStyles = makeStyles({
  page: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    height: '100%',
    minHeight: 0,
  },
  bar: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  filters: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalM,
    flexWrap: 'wrap',
  },
  grow: { flexGrow: 1 },
  muted: { color: tokens.colorNeutralForeground3 },
  list: {
    flexGrow: 1,
    minHeight: '240px',
    maxHeight: '60vh',
    overflow: 'auto',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    background: tokens.colorNeutralBackground2,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
  },
  wrap: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
  nowrap: { whiteSpace: 'pre', overflowX: 'auto' },
  entry: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke3}`,
    alignItems: 'baseline',
  },
  time: { color: tokens.colorNeutralForeground3, flexShrink: 0 },
  message: { flexGrow: 1, minWidth: 0 },
  logger: { color: tokens.colorNeutralForeground3 },
  warning: { background: tokens.colorPaletteMarigoldBackground1 },
  error: { background: tokens.colorPaletteRedBackground1 },
});

const LEVELS = [
  { value: '', label: 'All levels' },
  { value: 'debug', label: 'Debug and up' },
  { value: 'info', label: 'Info and up' },
  { value: 'warning', label: 'Warnings and errors' },
  { value: 'error', label: 'Errors only' },
];
const COLOURS = { debug: 'subtle', info: 'informative', warning: 'warning', error: 'danger' };

function timeOf(entry) {
  return entry.timestamp ? entry.timestamp.slice(11, 19) : '';
}

export function LogsPage() {
  const styles = useStyles();
  const [refresh, setRefresh] = useState(0);
  const [files, setFiles] = useState({ data: null, error: null, loading: true });
  const [component, setComponent] = useState('');
  const [day, setDay] = useState('');
  const [level, setLevel] = useState('');
  const [text, setText] = useState('');
  const [contains, setContains] = useState('');
  const [newestFirst, setNewestFirst] = useState(false);
  const [follow, setFollow] = useState(false);
  const [wrap, setWrap] = useState(true);
  const box = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    api.logs.list(controller.signal).then(
      (data) => setFiles({ data, error: null, loading: false }),
      (error) => error?.name !== 'AbortError' && setFiles({ data: null, error, loading: false }),
    );
    return () => controller.abort();
  }, [refresh]);

  // What is typed is applied a moment after the typing stops.
  useEffect(() => {
    const timer = setTimeout(() => setContains(text), 300);
    return () => clearTimeout(timer);
  }, [text]);

  const components = files.data?.components ?? [];
  const current =
    component || components.find((c) => c.exists)?.component || components[0]?.component || '';
  const info = components.find((c) => c.component === current);
  const days = info?.days ?? [];
  const order = newestFirst ? 'desc' : 'asc';
  const isToday = !day || day === days.at(-1);

  const log = useLogEntries({
    component: current,
    day,
    level,
    contains,
    order,
    follow: follow && isToday,
    refresh,
  });

  // Following keeps the end in view.
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [follow, log.items.length]);

  const params = useMemo(() => ({ day, level, contains, order }), [day, level, contains, order]);

  const componentOptions = components.map((c) => ({
    value: c.component,
    label: `${c.component}${c.exists ? ` (${formatBytes(c.size_bytes)})` : ' (empty)'}`,
  }));
  const dayOptions = [
    { value: '', label: 'Today' },
    ...[...days].reverse().map((d) => ({ value: d, label: d })),
  ];

  return (
    <div className={styles.page}>
      <PageHeader title="Logs" lead="What VethuQ and its parts have been doing." />
      <div className={styles.bar}>
        {componentOptions.length > 0 && (
          <FilterSelect
            label="Log"
            value={current}
            options={componentOptions}
            onChange={(value) => {
              setComponent(value);
              setDay('');
            }}
          />
        )}
        <FilterSelect label="Day" value={day} options={dayOptions} onChange={setDay} />
        <FilterSelect label="Level" value={level} options={LEVELS} onChange={setLevel} />
        <Input
          contentBefore={<Search20Regular />}
          contentAfter={
            text ? (
              <Button
                size="small"
                appearance="transparent"
                aria-label="Clear the search"
                icon={<Dismiss20Regular />}
                onClick={() => setText('')}
              />
            ) : undefined
          }
          placeholder="Search the messages"
          aria-label="Search the messages"
          value={text}
          onChange={(_, data) => setText(data.value)}
        />
        <span className={styles.grow} />
        <ToolButton
          label={follow ? 'Stop following' : 'Follow new entries'}
          icon={follow ? <Pause20Regular /> : <Play20Regular />}
          appearance={follow ? 'primary' : 'secondary'}
          disabled={!isToday}
          onClick={() => {
            setFollow((on) => !on);
            setNewestFirst(false);
          }}
        />
        <ToolButton
          label="Refresh"
          icon={<ArrowSync20Regular />}
          onClick={() => setRefresh((n) => n + 1)}
        />
        <ToolButton
          label="Export what is shown"
          icon={<ArrowDownload20Regular />}
          disabled={!log.exists || log.total === 0}
          onClick={() => download(api.logs.exportUrl(current, params))}
        />
      </div>
      <div className={styles.filters}>
        <Switch
          label="Newest first"
          checked={newestFirst}
          disabled={follow}
          onChange={(_, d) => setNewestFirst(d.checked)}
        />
        <Switch label="Wrap long lines" checked={wrap} onChange={(_, d) => setWrap(d.checked)} />
        <span className={styles.grow} />
        <Text className={styles.muted}>
          {log.total > log.items.length && !follow
            ? `Showing ${log.items.length} of ${log.total} entries`
            : `${log.total} entries`}
          {follow && isToday ? ' · following' : ''}
        </Text>
      </div>
      {info?.description && <Text className={styles.muted}>{info.description}</Text>}
      {(log.error || files.error) && (
        <MessageBar intent="error">
          <MessageBarBody>{(log.error ?? files.error).message}</MessageBarBody>
        </MessageBar>
      )}
      {(files.loading || log.loading) && <Spinner size="tiny" />}
      <div className={styles.list} ref={box} role="log" aria-label="Log entries">
        {!log.exists && <div className={styles.entry}>There is no log for this day yet.</div>}
        {log.exists && log.items.length === 0 && !log.loading && (
          <div className={styles.entry}>No entries match.</div>
        )}
        {log.items.map((entry, index) => (
          <div
            key={`${index}-${entry.timestamp}`}
            className={mergeClasses(
              styles.entry,
              entry.level === 'warning' && styles.warning,
              entry.level === 'error' && styles.error,
            )}
          >
            <span className={styles.time}>{timeOf(entry)}</span>
            <Badge appearance="tint" size="small" color={COLOURS[entry.level] ?? 'informative'}>
              {entry.level ?? '—'}
            </Badge>
            <span className={mergeClasses(styles.message, wrap ? styles.wrap : styles.nowrap)}>
              {entry.logger && <span className={styles.logger}>{entry.logger} </span>}
              {entry.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
