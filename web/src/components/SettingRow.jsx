import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  SpinButton,
  Spinner,
  Switch,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowCounterclockwise20Regular } from '@fluentui/react-icons';
import { useState } from 'react';
import { strings } from '../strings.js';
import { BandsControl } from './BandsControl.jsx';
import { PathControl } from './PathControl.jsx';
import { readSpin } from './numberInput.js';
import { SettingFrame } from './SettingFrame.jsx';

const text = strings.settings;

const useStyles = makeStyles({
  control: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1, minWidth: 0 },
  status: { width: '20px', display: 'inline-flex', justifyContent: 'center' },
  human: {
    color: tokens.colorNeutralForeground3,
    display: 'block',
    marginTop: tokens.spacingVerticalXXS,
  },
});

/** "10080" minutes as "7 days", for a figure that is easier to read that way. */
export function humanMinutes(minutes) {
  if (minutes === 0) return 'immediately';
  const units = [
    ['day', 1440],
    ['hour', 60],
    ['minute', 1],
  ];
  const [name, size] = units.find(([, size]) => minutes % size === 0) ?? units[2];
  const count = minutes / size;
  return `${count} ${name}${count === 1 ? '' : 's'}`;
}

/** Text as shown: a timestamp in the person's own format, anything else as it is. */
function formatText(value) {
  const stamp = /^\d{4}-\d\d-\d\dT/.test(value) ? new Date(value) : null;
  return stamp && !Number.isNaN(stamp.getTime()) ? stamp.toLocaleString() : String(value);
}

/** A value as the person would read it, for the "reset to" tooltip. */
function describe(setting, value) {
  if (setting.type === 'multichoice') {
    const names = (value ?? []).map(
      (item) => setting.options?.find((option) => option.value === item)?.label ?? item,
    );
    return names.length ? names.join(', ') : text.none;
  }
  if (setting.type === 'bands') return value.join(' / ');
  if (setting.type === 'text') return value === null ? text.none : formatText(value);
  if (setting.type === 'boolean') return value ? text.on : text.off;
  return String(setting.options?.find((option) => option.value === value)?.label ?? value);
}

/** The control for one setting, by its type. */
function Control({ setting, disabled, onChange }) {
  const styles = useStyles();
  const labelledBy = { 'aria-label': setting.label };

  if (setting.type === 'text') {
    if (setting.readonly) {
      return <Text>{setting.value === null ? text.none : formatText(setting.value)}</Text>;
    }
    return (
      <TextControl
        key={String(setting.value)}
        setting={setting}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }

  if (setting.type === 'boolean') {
    return (
      <Switch
        {...labelledBy}
        checked={setting.value === true}
        disabled={disabled}
        label={setting.value === true ? text.on : text.off}
        onChange={(_, data) => onChange(data.checked)}
      />
    );
  }

  if (setting.type === 'choice') {
    const options = setting.options ?? [];
    const selected = options.find((option) => option.value === setting.value);
    return (
      <Dropdown
        {...labelledBy}
        className={styles.grow}
        disabled={disabled}
        value={selected?.label ?? String(setting.value)}
        selectedOptions={[String(setting.value)]}
        onOptionSelect={(_, data) => {
          const chosen = options.find((option) => String(option.value) === data.optionValue);
          if (chosen && chosen.value !== setting.value) onChange(chosen.value);
        }}
      >
        {options.map((option) => (
          <Option
            key={String(option.value)}
            value={String(option.value)}
            text={option.label}
            disabled={!option.available}
          >
            {option.label}
            {!option.available && option.reason ? ` (${option.reason})` : ''}
          </Option>
        ))}
      </Dropdown>
    );
  }

  if (setting.type === 'multichoice') {
    const options = setting.options ?? [];
    const chosen = /** @type {string[]} */ (setting.value);
    return (
      <Dropdown
        {...labelledBy}
        multiselect
        className={styles.grow}
        disabled={disabled}
        placeholder={text.none}
        value={describe(setting, chosen) === text.none ? '' : describe(setting, chosen)}
        selectedOptions={chosen}
        onOptionSelect={(_, data) => onChange(data.selectedOptions)}
      >
        {options.map((option) => (
          <Option
            key={String(option.value)}
            value={String(option.value)}
            text={option.label}
            disabled={!option.available}
          >
            {option.label}
            {!option.available && option.reason ? ` (${option.reason})` : ''}
          </Option>
        ))}
      </Dropdown>
    );
  }

  return <NumberControl setting={setting} disabled={disabled} onChange={onChange} />;
}

/** Free text, saved on Enter or when the field is left. */
function TextControl({ setting, disabled, onChange }) {
  const styles = useStyles();
  const [draft, setDraft] = useState(String(setting.value ?? ''));
  const commit = () => {
    const next = draft.trim();
    if (next !== '' && next !== setting.value) onChange(next);
    else setDraft(String(setting.value ?? ''));
  };
  return (
    <Input
      aria-label={setting.label}
      className={styles.grow}
      disabled={disabled}
      value={draft}
      onChange={(_, data) => setDraft(data.value)}
      onBlur={commit}
      onKeyDown={(event) => event.key === 'Enter' && commit()}
    />
  );
}

/**
 * A number, saved when it is committed: stepping with the arrows, or Enter / leaving the field after
 * typing. (Fluent reports a typed number once, at that moment, as text.)
 */
function NumberControl({ setting, disabled, onChange }) {
  const styles = useStyles();
  return (
    <SpinButton
      aria-label={setting.label}
      className={styles.grow}
      disabled={disabled}
      value={Number(setting.value)}
      min={setting.min}
      max={setting.max}
      step={setting.type === 'integer' ? 1 : 0.5}
      precision={setting.type === 'integer' ? 0 : 1}
      onChange={(_, data) => {
        const { number } = readSpin(data);
        if (number !== null && number !== setting.value) onChange(number);
      }}
    />
  );
}

/**
 * One row of the settings screen: what the setting is, its control, a reset button, and why a
 * change was refused.
 *
 * @param {{ setting: import('../api/client.js').Setting, busy: boolean, problem: string,
 *   onChange: (value: unknown, options?: { move: boolean }) => Promise<boolean> | void,
 *   onReset: (options?: { move: boolean }) => Promise<boolean> | void }} props
 */
export function SettingRow({ setting, busy, problem, onChange, onReset }) {
  const styles = useStyles();
  const locked = Boolean(setting.locked);
  const hint = [setting.unit && `${text.unit}: ${setting.unit}`, setting.note, setting.locked]
    .filter(Boolean)
    .join(' · ');
  const wide = setting.type === 'bands' || setting.type === 'path';

  return (
    <SettingFrame
      testId={`setting-${setting.id}`}
      label={setting.label}
      description={setting.description}
      hint={hint}
      stacked={wide}
    >
      {setting.type === 'path' ? (
        <PathControl
          setting={setting}
          busy={busy}
          problem={problem}
          onChange={onChange}
          onReset={onReset}
        />
      ) : (
        <Field
          validationState={problem ? 'error' : 'none'}
          validationMessage={problem || undefined}
        >
          <div className={styles.control}>
            {setting.type === 'bands' ? (
              <BandsControl
                key={String(setting.value)}
                setting={setting}
                disabled={busy || locked}
                onChange={onChange}
              />
            ) : (
              <Control setting={setting} disabled={busy || locked} onChange={onChange} />
            )}
            <span className={styles.status}>{busy && <Spinner size="extra-tiny" />}</span>
            {setting.resettable !== false && (
              <Tooltip
                content={
                  setting.readonly
                    ? text.clear
                    : setting.default === null
                      ? text.reset
                      : `${text.resetTo} ${describe(setting, setting.default)}`
                }
                relationship="label"
              >
                <Button
                  appearance="subtle"
                  icon={<ArrowCounterclockwise20Regular />}
                  aria-label={`${setting.readonly ? text.clear : text.reset}: ${setting.label}`}
                  disabled={busy || locked || setting.is_default}
                  onClick={() => onReset()}
                />
              </Tooltip>
            )}
          </div>
        </Field>
      )}
      {setting.unit === 'minutes' && typeof setting.value === 'number' && (
        <Text size={200} className={styles.human}>
          {humanMinutes(setting.value)}
        </Text>
      )}
    </SettingFrame>
  );
}
