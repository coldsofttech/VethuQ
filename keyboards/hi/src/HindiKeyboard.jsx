import { Keyboard } from '@vethuq/keyboard-shared';
import { LAYERS, NAMES } from './layout.js';

/**
 * An on-screen Hindi keyboard: the shared keyboard with the Hindi (InScript) layout. See
 * `@vethuq/keyboard-shared` for the props.
 */
export function HindiKeyboard({ label = 'Hindi on-screen keyboard', ...props }) {
  return (
    <Keyboard layers={LAYERS} names={NAMES} label={label} lang="hi" fontSize={20} {...props} />
  );
}
