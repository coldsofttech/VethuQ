import { webDarkTheme, webLightTheme } from '@fluentui/react-components';
import { describe, expect, it } from 'vitest';
import { buildTheme } from './brandTheme.js';

const LIGHT = {
  primary: '#005FB8',
  'primary-hover': '#004A91',
  'primary-soft': '#E3EEF9',
  'on-primary': '#FFFFFF',
  bg: '#FAFAFA',
  surface: '#FFFFFF',
  text: '#1A1A1A',
  border: '#DDE3EA',
};

describe('buildTheme', () => {
  it('uses the stock Fluent theme when there is no palette', () => {
    expect(buildTheme('light', null)).toBe(webLightTheme);
    expect(buildTheme('dark', {})).toBe(webDarkTheme);
  });

  it('applies the brand palette on top of Fluent', () => {
    const theme = buildTheme('light', LIGHT);
    expect(theme.colorBrandBackground).toBe('#005FB8');
    expect(theme.colorBrandBackgroundHover).toBe('#004A91');
    expect(theme.colorCompoundBrandStroke).toBe('#005FB8');
    expect(theme.colorNeutralBackground3).toBe('#FAFAFA');
    expect(theme.colorNeutralForeground1).toBe('#1A1A1A');
  });

  it('keeps Fluent values for tokens the palette does not define', () => {
    const theme = buildTheme('light', { primary: '#005FB8' });
    expect(theme.colorNeutralBackground1).toBe(webLightTheme.colorNeutralBackground1);
    expect(theme.colorBrandBackgroundHover).toBe('#005FB8');
    expect(theme.fontFamilyBase).toBe(webLightTheme.fontFamilyBase);
  });
});
