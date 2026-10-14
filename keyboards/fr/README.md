# @vethuq/keyboard-fr

An on-screen French keyboard for VethuQ's search box: `@vethuq/keyboard-shared` with the French
layout. Like the viewers it lives outside `web/` and knows nothing about VethuQ or its API; it
reports the keys pressed and whoever uses it types into its own field.

```jsx
<FrenchKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'é' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- The layout is AZERTY, the French one. `é è à ù ç ê` have keys of their own; the other accented
  letters (`â î ô û ä ë ï ö ü ÿ`), the ligatures `œ æ`, the quotation marks `« »`, the apostrophe `’` and `€`
  are on the accents layer, one key away.
- Shift gives the capital of a letter, accented letters and ligatures included. The row of digits is
  ASCII, with no shift needed; the numbers and symbols layer has the symbols.
- The layout is data (`LAYERS` in `src/layout.js`).
