import {
  Button,
  Dropdown,
  Field,
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
import { strings } from '../strings.js';

const text = strings.settings;

const useStyles = makeStyles({
  row: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) minmax(220px, 300px)',
    gap: tokens.spacingHorizontalXXL,
    alignItems: 'start',
    padding: `${tokens.spacingVerticalM} 0`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  about: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS },
  hint: { color: tokens.colorNeutralForeground3 },
  control: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1, minWidth: 0 },
  status: { width: '20px', display: 'inline-flex', justifyContent: 'center' },
});

/** The control for one setting, by its type. */
function Control({ setting, disabled, onChange }) {
  const styles = useStyles();
  const labelledBy = { 'aria-label': setting.label };

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

  // integer and number
  const step = setting.type === 'integer' ? 1 : 0.5;
  return (
    <SpinButton
      {...labelledBy}
      className={styles.grow}
      disabled={disabled}
      value={Number(setting.value)}
      min={setting.min}
      max={setting.max}
      step={step}
      precision={setting.type === 'integer' ? 0 : 1}
      onChange={(_, data) => {
        // Only a committed number counts: stepping, or Enter/blur after typing.
        if (typeof data.value === 'number' && data.value !== setting.value) onChange(data.value);
      }}
    />
  );
}

/**
 * One row of the settings screen: what the setting is, its control, a reset button, and why a
 * change was refused.
 *
 * @param {{ setting: import('../api/client.js').Setting, busy: boolean, problem: string,
 *   onChange: (value: unknown) => void, onReset: () => void }} props
 */
export function SettingRow({ setting, busy, problem, onChange, onReset }) {
  const styles = useStyles();
  const hint = [setting.unit && `${text.unit}: ${setting.unit}`, setting.note]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className={styles.row} data-testid={`setting-${setting.id}`}>
      <div className={styles.about}>
        <Text weight="semibold">{setting.label}</Text>
        <Text className={styles.hint}>{setting.description}</Text>
        {hint && (
          <Text size={200} className={styles.hint}>
            {hint}
          </Text>
        )}
      </div>
      <Field validationState={problem ? 'error' : 'none'} validationMessage={problem || undefined}>
        <div className={styles.control}>
          <Control setting={setting} disabled={busy} onChange={onChange} />
          <span className={styles.status}>{busy && <Spinner size="extra-tiny" />}</span>
          <Tooltip
            content={`${text.resetTo} ${String(setting.options?.find((o) => o.value === setting.default)?.label ?? setting.default)}`}
            relationship="label"
          >
            <Button
              appearance="subtle"
              icon={<ArrowCounterclockwise20Regular />}
              aria-label={`${text.reset}: ${setting.label}`}
              disabled={busy || setting.is_default}
              onClick={onReset}
            />
          </Tooltip>
        </div>
      </Field>
    </div>
  );
}
