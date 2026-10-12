import {
  Body1,
  Card,
  CardHeader,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Text,
  Title2,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { CheckmarkCircle20Filled, Library20Regular, Rocket20Regular } from '@fluentui/react-icons';
import { api } from '../api/client.js';
import { useApi } from '../api/useApi.js';
import { useBrand } from '../brand/BrandProvider.jsx';
import { strings } from '../strings.js';

const useStyles = makeStyles({
  hero: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalL },
  logo: { width: '56px', height: '56px', flexShrink: 0 },
  heroText: { display: 'flex', flexDirection: 'column' },
  tagline: { color: tokens.colorNeutralForeground2 },
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL },
  cards: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: tokens.spacingHorizontalL,
  },
  card: { minHeight: '120px' },
  ready: { color: tokens.colorPaletteGreenForeground1, display: 'inline-flex' },
});

export function HomePage() {
  const styles = useStyles();
  const { data, error, loading } = useApi(api.about);
  const brand = useBrand();

  return (
    <div className={styles.page}>
      <div className={styles.hero}>
        <img className={styles.logo} src="/icon.svg" alt="" />
        <div className={styles.heroText}>
          <Title2 as="h1">{brand.name}</Title2>
          <Body1 className={styles.tagline}>{brand.tagline}</Body1>
        </div>
      </div>
      <Body1>{strings.home.welcome}</Body1>
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{strings.errors.loadFailed}</MessageBarTitle>
          </MessageBarBody>
        </MessageBar>
      )}
      <div className={styles.cards}>
        <Card className={styles.card}>
          <CardHeader
            image={<CheckmarkCircle20Filled className={styles.ready} />}
            header={<Text weight="semibold">{strings.home.engineTitle}</Text>}
            description={<Text>{strings.home.engineReady}</Text>}
          />
          {loading ? (
            <Spinner size="tiny" />
          ) : (
            data && <Body1>{strings.home.engineVersion(data.vethuq)}</Body1>
          )}
        </Card>
        <Card className={styles.card}>
          <CardHeader
            image={<Library20Regular />}
            header={<Text weight="semibold">{strings.home.environmentTitle}</Text>}
          />
          {loading ? (
            <Spinner size="tiny" />
          ) : (
            data && (
              <Body1>
                Python {data.python} · {data.platform}
              </Body1>
            )
          )}
        </Card>
        <Card className={styles.card}>
          <CardHeader
            image={<Rocket20Regular />}
            header={<Text weight="semibold">{strings.home.startedTitle}</Text>}
          />
          <Body1>{strings.home.startedBody}</Body1>
        </Card>
      </div>
    </div>
  );
}
