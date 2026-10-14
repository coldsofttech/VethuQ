import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen Urdu keyboard: the shared keyboard with the Urdu layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function UrduKeyboard({ label = 'Urdu on-screen keyboard', ...props }) {
  return (
    <Keyboard layers={LAYERS} names={NAMES} label={label} lang="ur" fontSize={20} {...props} />
  );
}
