# @vethuq/keyboard-shared

What the on-screen keyboards (`keyboards/en`, `keyboards/te`, ...) have in common: the keyboard
itself, which a language fills with its layout, and helpers to write a layout. Like the viewers it
lives outside `web/`, knows nothing about VethuQ or its API, and has no dependency but React (a peer).

```jsx
<Keyboard
  layers={LAYERS}       // the layout: { layer: rows of keys }, the first layer is shown first
  names={NAMES}         // what a screen reader says for a character (optional)
  label="English on-screen keyboard"
  lang="en"             // the language of the keys (optional)
  fontSize={16}         // the size of the letters on the keys, in pixels (optional)
  onKey={(key) => ...}  // { type: 'text', value } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- Shift (one key, then back; press again for caps lock) types a key's `shift` character: a capital
  for English, another letter for a script with no case. The space key types `' '`.
- A key's sign that only sits on a letter (a vowel sign) is drawn on a dotted circle.
- Pressing a key with the mouse or a finger keeps the focus in the field being typed into. Keys are
  buttons with names a screen reader can say; shift and caps lock report `aria-pressed`.
- Colours follow the Fluent UI theme variables when the page has them.

## Writing a language

A layout is data (`src/layout.js` explains the keys). `keys('abc', 'ABC')` makes the keys, and
`bottomRow` and `symbolsLayer` give the parts every language shares:

```js
export const LAYERS = {
  letters: [keys('qwerty...', 'QWERTY...'), ..., bottomRow(toSymbols)],
  symbols: symbolsLayer('1234567890', toLetters),
};
export const Keyboard = (props) => <Keyboard layers={LAYERS} names={NAMES} lang="xx" {...props} />;
```

Add the new folder to `web/` (`package.json`, the lint script, `src/search/keyboards.js`).
