import { Radio, RadioGroup, Tab, TabList, makeStyles, tokens } from '@fluentui/react-components';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader.jsx';
import { SettingFrame } from '../components/SettingFrame.jsx';
import { SettingsSection } from '../components/SettingsSection.jsx';
import { strings } from '../strings.js';
import { useTheme } from '../theme/ThemeProvider.jsx';

const SECTIONS = ['general', 'indexing', 'sources', 'tiers', 'results'];

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
});

function General() {
  const { choice, setChoice } = useTheme();
  return (
    <div>
      <SettingFrame
        label={strings.settings.themeTitle}
        description={strings.settings.themeDescription}
        testId="setting-theme"
      >
        <RadioGroup
          aria-label={strings.settings.themeTitle}
          value={choice}
          onChange={(_, data) => setChoice(data.value)}
        >
          <Radio value="system" label={strings.settings.themeSystem} />
          <Radio value="light" label={strings.settings.themeLight} />
          <Radio value="dark" label={strings.settings.themeDark} />
        </RadioGroup>
      </SettingFrame>
      <SettingsSection section="general" />
    </div>
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
        {SECTIONS.filter((id) => id !== 'general').map((id) => (
          <Route key={id} path={id} element={<SettingsSection section={id} />} />
        ))}
        <Route path="*" element={<Navigate to="general" replace />} />
      </Routes>
    </div>
  );
}
