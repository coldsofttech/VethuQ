# @vethuq/keyboard-en

An on-screen English (QWERTY) keyboard, for VethuQ's search box. Like the viewers it lives outside
`web/`, knows nothing about VethuQ or its API, and has no dependency but React and the shared keyboard (peers). It edits
nothing itself: it reports the keys pressed and whoever uses it types into its own field. It is
`@vethuq/keyboard-shared` with the English layout, which is where the keys and shift are described.

```jsx
<EnglishKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'A' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
  label="English on-screen keyboard" // for a screen reader (optional)
/>
```

- Letters with shift (one capital, then back; press again for caps lock) and a layer of numbers and
  symbols. The space key types `' '`.
- Pressing a key with the mouse or a finger keeps the focus in the field being typed into.
- Keys are buttons with names a screen reader can say; shift and caps lock report `aria-pressed`.
- The layout is data (`LAYERS` in `src/layout.js`); another language is another folder in
  `keyboards/` (see `keyboards/shared`, and `keyboards/te` for Telugu).
- Colours follow the Fluent UI theme variables when the page has them.
