import { Field, Radio, RadioGroup, makeStyles, tokens } from '@fluentui/react-components';
import { PageHeader } from '../components/PageHeader.jsx';
import { strings } from '../strings.js';
import { useTheme } from '../theme/ThemeProvider.jsx';

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL },
});

export function SettingsPage() {
  const styles = useStyles();
  const { choice, setChoice } = useTheme();

  return (
    <div className={styles.page}>
      <PageHeader title={strings.settings.title} lead={strings.settings.lead} />
      <Field label={strings.settings.themeTitle}>
        <RadioGroup value={choice} onChange={(_, data) => setChoice(data.value)}>
          <Radio value="system" label={strings.settings.themeSystem} />
          <Radio value="light" label={strings.settings.themeLight} />
          <Radio value="dark" label={strings.settings.themeDark} />
        </RadioGroup>
      </Field>
    </div>
  );
}
