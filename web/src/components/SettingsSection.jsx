import {
  Body1,
  MessageBar,
  MessageBarBody,
  Spinner,
  Switch,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Fragment, useState } from 'react';
import { useSettings } from '../settings/useSettings.js';
import { strings } from '../strings.js';
import { GroupHeading } from './GroupHeading.jsx';
import { SettingRow } from './SettingRow.jsx';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    maxWidth: '900px',
  },
  empty: { color: tokens.colorNeutralForeground3 },
});

/**
 * Every setting of one section, under group headings, with a switch that reveals the advanced ones.
 *
 * @param {{ section: string, empty?: string }} props  `empty` is said when the section has none.
 */
export function SettingsSection({ section, empty = strings.settings.noSettings }) {
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
      {!loading && !error && settings.length === 0 && (
        <Body1 className={styles.empty}>{empty}</Body1>
      )}
      {shown.map((setting, index) => {
        const previous = shown[index - 1];
        const heading = setting.group && setting.group !== previous?.group;
        return (
          <Fragment key={setting.id}>
            {heading && <GroupHeading title={setting.group} note={setting.group_note} />}
            <SettingRow
              setting={setting}
              busy={busy[setting.id] === true}
              problem={problems[setting.id] ?? ''}
              onChange={(value, options) => update(setting.id, value, options)}
              onReset={(options) => reset(setting.id, options)}
            />
          </Fragment>
        );
      })}
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
