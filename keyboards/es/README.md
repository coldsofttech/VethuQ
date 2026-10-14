# @vethuq/keyboard-es

An on-screen Spanish keyboard for VethuQ's search box: `@vethuq/keyboard-shared` with the Spanish
layout. Like the viewers it lives outside `web/` and knows nothing about VethuQ or its API; it
reports the keys pressed and whoever uses it types into its own field.

```jsx
<SpanishKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'é' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- The layout is QWERTY with `ñ` after `l`. The accented vowels `á é í ó ú` and `ü` have keys of
  their own, and `¿ ¡` are by the full stop.
- Shift gives the capital of a letter, accented letters and ligatures included. The row of digits is
  ASCII, with no shift needed; the numbers and symbols layer has the symbols.
- The layout is data (`LAYERS` in `src/layout.js`).
