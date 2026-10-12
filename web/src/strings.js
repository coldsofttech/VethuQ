// Every user-visible string lives here so the interface can be translated later.
export const strings = {
  appName: 'VethuQ',
  tagline: 'Document intelligence and evidence infrastructure',
  nav: { home: 'Home', about: 'About', settings: 'Settings' },
  window: {
    minimize: 'Minimize',
    maximize: 'Maximize',
    restore: 'Restore',
    close: 'Close',
  },
  home: {
    title: 'Welcome to VethuQ',
    lead: 'Search, retrieve and structure your documents, offline and on your own machine.',
    engineTitle: 'Engine',
    engineReady: 'Ready',
    engineVersion: (version) => `VethuQ ${version}`,
    environmentTitle: 'Environment',
    startedTitle: 'Getting started',
    startedBody: 'Sources, search and exports will appear here as they are added to the interface.',
  },
  about: {
    title: 'About',
    lead: 'What this installation is running.',
    rows: {
      vethuq: 'VethuQ',
      python: 'Python',
      platform: 'Platform',
      db_schema: 'Database schema',
    },
  },
  settings: {
    title: 'Settings',
    lead: 'Personalise how VethuQ looks.',
    themeTitle: 'Theme',
    themeSystem: 'Use my system setting',
    themeLight: 'Light',
    themeDark: 'Dark',
  },
  errors: {
    offlineTitle: 'Cannot reach the VethuQ service',
    offlineBody: 'The local service is not responding. Close and reopen the application.',
    loadFailed: 'Could not load this information.',
  },
};
