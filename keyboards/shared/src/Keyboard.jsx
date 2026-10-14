import { useState } from 'react';

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

const FIXED = {
  shift: { label: '⇧', name: 'Shift' },
  backspace: { label: '⌫', name: 'Backspace' },
  enter: { label: '⏎', name: 'Enter' },
  space: { label: 'space', name: 'Space' },
  close: { label: '⌄', name: 'Hide keyboard' },
};

/** What a text key types: its shifted character while shift is on, if it has one. */
export function typedValue(key, shifted) {
  return shifted && key.shift ? key.shift : key.value;
}

// A sign that only sits on a letter (a vowel sign, a virama) is shown on a dotted circle.
const shown = (value) => (/^\p{M}$/u.test(value) ? `◌${value}` : value);

/**
 * An on-screen keyboard for a layout (see layout.js). It edits nothing: it says which key was
 * pressed, and whoever uses it types into its own field. Pressing a key keeps the focus where it was.
 *
 * @param {object} props
 * @param {Record<string, object[][]>} props.layers the layout; the first layer is shown first
 * @param {(key: {type: 'text', value: string} | {type: 'backspace'} | {type: 'enter'}) => void}
 *   props.onKey a key was pressed (the space key types ' ')
 * @param {() => void} [props.onClose] the hide key was pressed
 * @param {Record<string, string>} [props.names] what a screen reader says for a character
 * @param {string} props.label the name of the keyboard for a screen reader
 * @param {string} [props.lang] the language of the keys
 * @param {number} [props.fontSize] the size of the letters on the keys, in pixels (16)
 */
export function Keyboard({ layers, onKey, onClose, names = {}, label, lang, fontSize = 16 }) {
  const [layer, setLayer] = useState(() => Object.keys(layers)[0]);
  const [shift, setShift] = useState('off'); // 'off', 'once' (the next key) or 'caps'

  const press = (key) => {
    switch (key.type) {
      case 'text':
        onKey({ type: 'text', value: typedValue(key, shift !== 'off') });
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
      const value = typedValue(key, shift !== 'off');
      return { label: shown(value), name: names[value] ?? value };
    }
    if (key.type === 'layer') return { label: key.label, name: key.name ?? key.label };
    if (key.type === 'shift') {
      return {
        label: shift === 'caps' ? '⇪' : FIXED.shift.label,
        name: shift === 'caps' ? 'Caps lock' : 'Shift',
        pressed: shift !== 'off',
      };
    }
    return FIXED[key.type];
  };

  return (
    // The keys sit where the physical keys are, left to right, whatever way the language reads.
    <div role="group" aria-label={label} style={css.root} lang={lang} dir="ltr">
      {layers[layer].map((row, r) => (
        <div key={r} style={css.row}>
          {row.map((key, k) => {
            const { label: text, name, pressed } = describe(key);
            return (
              <button
                key={k}
                type="button"
                aria-label={name}
                aria-pressed={pressed}
                style={{
                  ...css.key,
                  fontSize,
                  flexGrow: key.width ?? 1,
                  ...(key.type === 'shift' && shift !== 'off' ? css.active : null),
                }}
                // Keep the focus (and the caret) in the field being typed into.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => press(key)}
              >
                {text}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
