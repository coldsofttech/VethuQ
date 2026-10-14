import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen English keyboard: the shared keyboard with the English layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function EnglishKeyboard({ label = 'English on-screen keyboard', ...props }) {
  return <Keyboard layers={LAYERS} names={NAMES} label={label} lang="en" {...props} />;
}
