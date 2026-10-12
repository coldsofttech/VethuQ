import { webDarkTheme, webLightTheme } from '@fluentui/react-components';

/**
 * The Fluent theme for one colour scheme, with VethuQ's palette applied on top.
 *
 * The palette (`primary`, `surface`, `text`, ...) is the core's design tokens, shared with the CLI
 * and the HTML export. Fluent's stock theme supplies everything the palette does not name (hover
 * shades of greys, shadows, typography), so a missing palette simply gives stock Fluent.
 *
 * @param {'light' | 'dark'} scheme
 * @param {import('../api/client.js').PaletteScheme | null | undefined} palette
 */
export function buildTheme(scheme, palette) {
  const base = scheme === 'dark' ? webDarkTheme : webLightTheme;
  if (!palette || !palette.primary) return base;
  const p = palette;
  const hover = p['primary-hover'] ?? p.primary;

  return {
    ...base,

    // Brand colour: buttons, selection, links, focus.
    colorBrandBackground: p.primary,
    colorBrandBackgroundHover: hover,
    colorBrandBackgroundPressed: hover,
    colorBrandBackgroundSelected: p.primary,
    colorBrandBackground2: p['primary-soft'] ?? base.colorBrandBackground2,
    colorBrandForeground1: p.primary,
    colorBrandForeground2: hover,
    colorBrandForegroundLink: p.primary,
    colorBrandForegroundLinkHover: hover,
    colorBrandForegroundLinkPressed: hover,
    colorBrandForegroundLinkSelected: p.primary,
    colorBrandStroke1: p.primary,
    colorCompoundBrandBackground: p.primary,
    colorCompoundBrandBackgroundHover: hover,
    colorCompoundBrandBackgroundPressed: hover,
    colorCompoundBrandForeground1: p.primary,
    colorCompoundBrandForeground1Hover: hover,
    colorCompoundBrandForeground1Pressed: hover,
    colorCompoundBrandStroke: p.primary,
    colorCompoundBrandStrokeHover: hover,
    colorCompoundBrandStrokePressed: hover,
    colorNeutralForegroundOnBrand: p['on-primary'] ?? base.colorNeutralForegroundOnBrand,

    // Surfaces and text.
    colorNeutralBackground1: p.surface ?? base.colorNeutralBackground1,
    colorNeutralBackground2: p['surface-alt'] ?? base.colorNeutralBackground2,
    colorNeutralBackground3: p.bg ?? base.colorNeutralBackground3,
    colorNeutralForeground1: p.text ?? base.colorNeutralForeground1,
    colorNeutralForeground2: p['text-muted'] ?? base.colorNeutralForeground2,
    colorNeutralForeground3: p['text-muted'] ?? base.colorNeutralForeground3,
    colorNeutralStroke1: p.border ?? base.colorNeutralStroke1,
    colorNeutralStroke2: p['border-soft'] ?? base.colorNeutralStroke2,

    // Status colours.
    colorStatusSuccessForeground1: p.success ?? base.colorStatusSuccessForeground1,
    colorPaletteGreenForeground1: p.success ?? base.colorPaletteGreenForeground1,
    colorPaletteGreenForeground2: p.success ?? base.colorPaletteGreenForeground2,
    colorStatusWarningForeground1: p.warning ?? base.colorStatusWarningForeground1,
    colorStatusWarningBackground1: p['warning-bg'] ?? base.colorStatusWarningBackground1,
    colorStatusDangerForeground1: p.danger ?? base.colorStatusDangerForeground1,
    colorPaletteRedForeground1: p.danger ?? base.colorPaletteRedForeground1,
  };
}
