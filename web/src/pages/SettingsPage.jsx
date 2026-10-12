import {
  Field,
  Radio,
  RadioGroup,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader.jsx';
import { SettingsSection } from '../components/SettingsSection.jsx';
import { strings } from '../strings.js';
import { useTheme } from '../theme/ThemeProvider.jsx';

const SECTIONS = ['general', 'indexing'];

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
});

function General() {
  const { choice, setChoice } = useTheme();
  return (
    <Field label={strings.settings.themeTitle}>
      <RadioGroup value={choice} onChange={(_, data) => setChoice(data.value)}>
        <Radio value="system" label={strings.settings.themeSystem} />
        <Radio value="light" label={strings.settings.themeLight} />
        <Radio value="dark" label={strings.settings.themeDark} />
      </RadioGroup>
    </Field>
  );
}

export function SettingsPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const current = SECTIONS.find((id) => pathname.endsWith(`/${id}`)) ?? SECTIONS[0];

  return (
    <div className={styles.page}>
      <PageHeader title={strings.settings.title} lead={strings.settings.lead} />
      <TabList
        selectedValue={current}
        onTabSelect={(_, data) => navigate(`/settings/${data.value}`)}
      >
        {SECTIONS.map((id) => (
          <Tab key={id} value={id}>
            {strings.settings.sections[id]}
          </Tab>
        ))}
      </TabList>
      <Routes>
        <Route index element={<Navigate to="general" replace />} />
        <Route path="general" element={<General />} />
        <Route path="indexing" element={<SettingsSection section="indexing" />} />
        <Route path="*" element={<Navigate to="general" replace />} />
      </Routes>
    </div>
  );
}
