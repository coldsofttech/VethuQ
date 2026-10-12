import {
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { formatDuration } from '../format.js';
import { useIndexing } from '../indexing/IndexingProvider.jsx';
import { BarChart } from '../credits/BarChart.jsx';
import { formatCredits } from '../format.js';
import { toParams } from './filters.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
  cards: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
    gap: tokens.spacingHorizontalM,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingVerticalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
  },
  wide: { gridColumn: 'span 2' },
  muted: { color: tokens.colorNeutralForeground3 },
  split: {
    display: 'flex',
    height: '10px',
    borderRadius: '5px',
    overflow: 'hidden',
    background: tokens.colorNeutralBackground5,
  },
  legend: { display: 'flex', gap: tokens.spacingHorizontalL, flexWrap: 'wrap' },
  key: { display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalXS },
  swatch: { width: '10px', height: '10px', borderRadius: '2px', display: 'inline-block' },
});

const BAND_COLOURS = {
  high: tokens.colorPaletteGreenBackground3,
  medium: tokens.colorPaletteMarigoldBackground3,
  low: tokens.colorPaletteDarkOrangeBackground3,
  unreliable: tokens.colorPaletteRedBackground3,
};
const NATIVE = tokens.colorBrandBackground;
const OCR = tokens.colorPaletteMarigoldBackground3;

function Card({ title, value, note, wide, children }) {
  const styles = useStyles();
  return (
    <div className={`${styles.card} ${wide ? styles.wide : ''}`}>
      <Text className={styles.muted}>{title}</Text>
      <Text size={700} weight="semibold">
        {value}
      </Text>
      {note && <Text className={styles.muted}>{note}</Text>}
      {children}
    </div>
  );
}

/** A bar split into parts: `parts` are `{ key, label, value, colour }`. */
function Split({ parts, empty }) {
  const styles = useStyles();
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (total === 0) return <Text className={styles.muted}>{empty}</Text>;
  return (
    <div>
      <div
        className={styles.split}
        role="img"
        aria-label={parts.map((p) => `${p.label} ${p.value}`).join(', ')}
      >
        {parts.map((p) => (
          <span
            key={p.key}
            style={{ width: `${(p.value / total) * 100}%`, background: p.colour }}
          />
        ))}
      </div>
      <div className={styles.legend}>
        {parts.map((p) => (
          <span key={p.key} className={styles.key}>
            <span className={styles.swatch} style={{ background: p.colour }} />
            {p.label}: {p.value.toLocaleString()}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SummaryTab({ filters, refresh }) {
  const styles = useStyles();
  const { version } = useIndexing();
  const params = useMemo(() => toParams(filters), [filters]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    api.stats.summary(params, controller.signal).then(
      (result) => {
        setData(result);
        setError(null);
      },
      (failure) => failure?.name !== 'AbortError' && setError(failure),
    );
    return () => controller.abort();
  }, [params, version, refresh]);

  if (error)
    return (
      <MessageBar intent="error">
        <MessageBarBody>{error.message}</MessageBarBody>
      </MessageBar>
    );
  if (!data) return <Spinner size="small" label="Loading statistics" />;

  const t = data.total;
  const minutes = t.duration_ms / 60000;
  return (
    <div className={styles.root}>
      <div className={styles.cards}>
        <Card title="Files indexed" value={(t.files ?? 0).toLocaleString()} />
        <Card title="Pages read" value={t.pages.toLocaleString()} note="Native text and OCR" />
        <Card
          title="Average confidence"
          value={t.confidence == null ? '—' : `${Math.round(t.confidence * 100)}%`}
          note="Across the pages read"
        />
        <Card
          title="OCR time"
          value={t.duration_ms ? formatDuration(t.duration_ms / 1000) : '—'}
          note={
            t.ocr_pages && minutes > 0
              ? `${(t.ocr_pages / minutes).toFixed(1)} pages a minute`
              : 'No OCR yet'
          }
        />
        <Card title="Credits spent" value={formatCredits(t.credits)} />
        <Card title="Failed files" value={(t.failures ?? 0).toLocaleString()} />
        <Card wide title="How pages were read">
          <Split
            empty="No pages read yet."
            parts={[
              { key: 'native', label: 'Native text', value: t.native_pages, colour: NATIVE },
              { key: 'ocr', label: 'OCR', value: t.ocr_pages, colour: OCR },
            ]}
          />
        </Card>
        <Card wide title="Confidence of OCR pages">
          <Split
            empty="No OCR pages yet."
            parts={['high', 'medium', 'low', 'unreliable'].map((band) => ({
              key: band,
              label: band.charAt(0).toUpperCase() + band.slice(1),
              value: t.bands?.[band] ?? 0,
              colour: BAND_COLOURS[band],
            }))}
          />
        </Card>
      </div>
      <Text weight="semibold">Pages read per day</Text>
      <BarChart
        days={data.days}
        series={['native', 'ocr']}
        labels={{ native: 'Native text', ocr: 'OCR' }}
        unit="pages"
        description="Pages read per day"
      />
    </div>
  );
}
