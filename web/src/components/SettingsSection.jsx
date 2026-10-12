import {
  MessageBar,
  MessageBarBody,
  Spinner,
  Switch,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { strings } from '../strings.js';
import { useSettings } from '../settings/useSettings.js';
import { SettingRow } from './SettingRow.jsx';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    maxWidth: '900px',
  },
});

/** Every setting of one section, with a switch that reveals the advanced ones. */
export function SettingsSection({ section }) {
  const styles = useStyles();
  const { settings, loading, error, busy, problems, update, reset } = useSettings(section);
  const [advanced, setAdvanced] = useState(false);
  const hasAdvanced = settings.some((setting) => setting.advanced);
  const shown = settings.filter((setting) => advanced || !setting.advanced);

  return (
    <div className={styles.root}>
      {loading && <Spinner size="small" />}
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{strings.errors.loadFailed}</MessageBarBody>
        </MessageBar>
      )}
      {shown.map((setting) => (
        <SettingRow
          key={setting.id}
          setting={setting}
          busy={busy[setting.id] === true}
          problem={problems[setting.id] ?? ''}
          onChange={(value) => update(setting.id, value)}
          onReset={() => reset(setting.id)}
        />
      ))}
      {hasAdvanced && (
        <Switch
          checked={advanced}
          label={strings.settings.showAdvanced}
          onChange={(_, data) => setAdvanced(data.checked)}
        />
      )}
    </div>
  );
}
