import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen French keyboard: the shared keyboard with the French layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function FrenchKeyboard({ label = 'French on-screen keyboard', ...props }) {
  return <Keyboard layers={LAYERS} names={NAMES} label={label} lang="fr" {...props} />;
}
