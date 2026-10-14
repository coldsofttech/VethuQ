import { useState } from 'react';
import { LAYERS, NAMES } from './layout.js';

const css = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    padding: 8,
    boxSizing: 'border-box',
    userSelect: 'none',
    touchAction: 'manipulation',
    background: 'var(--colorNeutralBackground3, #f0f0f0)',
    borderRadius: 'var(--borderRadiusMedium, 4px)',
  },
  row: { display: 'flex', gap: 6 },
  key: {
    flex: '1 1 0',
    minWidth: 0,
    minHeight: 44,
    padding: 0,
    font: 'inherit',
    fontSize: 16,
    cursor: 'pointer',
    color: 'var(--colorNeutralForeground1, #242424)',
    background: 'var(--colorNeutralBackground1, #fff)',
    border: '1px solid var(--colorNeutralStroke1, #d1d1d1)',
    borderRadius: 'var(--borderRadiusMedium, 4px)',
  },
  active: {
    color: 'var(--colorNeutralForegroundOnBrand, #fff)',
    background: 'var(--colorBrandBackground, #0f6cbd)',
    borderColor: 'var(--colorBrandBackground, #0f6cbd)',
  },
};

/** What a shifted key types: a letter becomes its capital, anything else stays. */
export function applyShift(value, shifted) {
  return shifted && /^[a-z]$/.test(value) ? value.toUpperCase() : value;
}

const FIXED = {
  shift: { label: '⇧', name: 'Shift' },
  backspace: { label: '⌫', name: 'Backspace' },
  enter: { label: '⏎', name: 'Enter' },
  space: { label: 'space', name: 'Space' },
  close: { label: '⌄', name: 'Hide keyboard' },
};

/**
 * An on-screen English keyboard. It edits nothing: it says which key was pressed, and whoever
 * uses it types into its own field. Pressing a key keeps the focus where it was.
 *
 * @param {object} props
 * @param {(key: {type: 'text', value: string} | {type: 'backspace'} | {type: 'enter'}) => void}
 *   props.onKey a key was pressed (the space key types ' ')
 * @param {() => void} [props.onClose] the hide key was pressed
 * @param {string} [props.label] the name of the keyboard for a screen reader
 */
export function EnglishKeyboard({ onKey, onClose, label = 'English on-screen keyboard' }) {
  const [layer, setLayer] = useState('letters');
  const [shift, setShift] = useState('off'); // 'off', 'once' (the next letter) or 'caps'

  const press = (key) => {
    switch (key.type) {
      case 'text':
        onKey({ type: 'text', value: applyShift(key.value, shift !== 'off') });
        if (shift === 'once') setShift('off');
        break;
      case 'space':
        onKey({ type: 'text', value: ' ' });
        if (shift === 'once') setShift('off');
        break;
      case 'shift':
        setShift(shift === 'off' ? 'once' : shift === 'once' ? 'caps' : 'off');
        break;
      case 'layer':
        setLayer(key.to);
        setShift('off');
        break;
      case 'close':
        onClose?.();
        break;
      default:
        onKey({ type: key.type });
    }
  };

  const describe = (key) => {
    if (key.type === 'text') {
      const shown = applyShift(key.value, shift !== 'off');
      return { label: shown, name: NAMES[key.value] ?? shown, pressed: undefined };
    }
    if (key.type === 'layer') {
      return {
        label: key.label,
        name: key.to === 'symbols' ? 'Numbers and symbols' : 'Letters',
        pressed: undefined,
      };
    }
    if (key.type === 'shift') {
      return {
        label: shift === 'caps' ? '⇪' : FIXED.shift.label,
        name: shift === 'caps' ? 'Caps lock' : 'Shift',
        pressed: shift !== 'off',
      };
    }
    return { ...FIXED[key.type], pressed: undefined };
  };

  return (
    <div role="group" aria-label={label} style={css.root} lang="en">
      {LAYERS[layer].map((row, r) => (
        <div key={r} style={css.row}>
          {row.map((key, k) => {
            const { label: shown, name, pressed } = describe(key);
            return (
              <button
                key={k}
                type="button"
                aria-label={name}
                aria-pressed={pressed}
                style={{
                  ...css.key,
                  flexGrow: key.width ?? 1,
                  ...(key.type === 'shift' && shift !== 'off' ? css.active : null),
                }}
                // Keep the focus (and the caret) in the field being typed into.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => press(key)}
              >
                {shown}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
