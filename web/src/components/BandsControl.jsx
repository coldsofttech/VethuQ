import {
  Button,
  SpinButton,
  Text,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { strings } from '../strings.js';
import { readSpin } from './numberInput.js';

const text = strings.settings;

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    maxWidth: '520px',
  },
  fields: { display: 'flex', gap: tokens.spacingHorizontalM, flexWrap: 'wrap', alignItems: 'end' },
  field: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
    width: '110px',
  },
  bar: {
    display: 'flex',
    height: '12px',
    borderRadius: tokens.borderRadiusMedium,
    overflow: 'hidden',
    background: tokens.colorNeutralBackground5,
  },
  captions: { display: 'flex', color: tokens.colorNeutralForeground3 },
  caption: { overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' },
  unreliable: { background: tokens.colorPaletteRedBackground3 },
  low: { background: tokens.colorPaletteDarkOrangeBackground3 },
  medium: { background: tokens.colorPaletteYellowBackground3 },
  high: { background: tokens.colorPaletteGreenBackground3 },
  error: { color: tokens.colorPaletteRedForeground1 },
});

const rising = (bands) =>
  bands[0] >= 0 && bands[0] < bands[1] && bands[1] < bands[2] && bands[2] <= 100;

/**
 * Three whole percentages that must rise, saved together with Apply. The parent gives it a `key`
 * made of the saved value, so the draft starts over after a save, a reset or a refused change. A bar shows what the bands
 * mean: below the first is unreliable, then low, medium and high.
 *
 * @param {{ setting: import('../api/client.js').Setting, disabled: boolean,
 *   onChange: (value: number[]) => void }} props
 */
export function BandsControl({ setting, disabled, onChange }) {
  const styles = useStyles();
  const saved = /** @type {number[]} */ (setting.value);
  const [draft, setDraft] = useState(saved);

  const labels = setting.labels ?? [];
  const valid = rising(draft);
  const changed = draft.join(',') !== saved.join(',');
  const segments = [
    { key: 'unreliable', width: draft[0], label: text.bands.unreliable },
    { key: 'low', width: draft[1] - draft[0], label: text.bands.names[0] },
    { key: 'medium', width: draft[2] - draft[1], label: text.bands.names[1] },
    { key: 'high', width: 100 - draft[2], label: text.bands.names[2] },
  ].map((segment) => ({ ...segment, width: Math.max(0, segment.width) }));

  return (
    <div className={styles.root}>
      <div className={styles.fields}>
        {labels.map((label, index) => (
          <div key={label} className={styles.field}>
            <Text size={200}>{label}</Text>
            <SpinButton
              aria-label={label}
              disabled={disabled}
              value={draft[index]}
              min={0}
              max={100}
              step={1}
              onChange={(_, data) => {
                const { number } = readSpin(data);
                if (number === null) return;
                setDraft((current) => current.map((v, i) => (i === index ? number : v)));
              }}
            />
          </div>
        ))}
        <Button
          appearance="primary"
          disabled={disabled || !changed || !valid}
          onClick={() => onChange(draft)}
        >
          {text.apply}
        </Button>
      </div>
      {!valid && <Text className={styles.error}>{text.bands.invalid}</Text>}
      <div className={styles.bar} aria-hidden="true">
        {segments.map((segment) => (
          <div
            key={segment.key}
            className={mergeClasses(styles[segment.key])}
            style={{ width: `${segment.width}%` }}
            title={`${segment.label}`}
          />
        ))}
      </div>
      <div className={styles.captions} aria-hidden="true">
        {segments.map((segment) => (
          <Text
            size={200}
            key={segment.key}
            className={styles.caption}
            style={{ width: `${segment.width}%` }}
          >
            {segment.label}
          </Text>
        ))}
      </div>
    </div>
  );
}
