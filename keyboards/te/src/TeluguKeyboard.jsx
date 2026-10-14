import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen Telugu keyboard: the shared keyboard with the Telugu (InScript) layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function TeluguKeyboard({ label = 'Telugu on-screen keyboard', ...props }) {
  return (
    <Keyboard layers={LAYERS} names={NAMES} label={label} lang="te" fontSize={20} {...props} />
  );
}
