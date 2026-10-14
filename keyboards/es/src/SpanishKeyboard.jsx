import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen Spanish keyboard: the shared keyboard with the Spanish layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function SpanishKeyboard({ label = 'Spanish on-screen keyboard', ...props }) {
  return <Keyboard layers={LAYERS} names={NAMES} label={label} lang="es" {...props} />;
}
