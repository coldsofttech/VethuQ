# @vethuq/keyboard-ur

An on-screen Urdu keyboard for VethuQ's search box: `@vethuq/keyboard-shared` with the Urdu layout.
Like the viewers it lives outside `web/` and knows nothing about VethuQ or its API; it reports the
keys pressed and whoever uses it types into its own field.

```jsx
<UrduKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'ق' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- Urdu script has no InScript-style standard that keyboards agree on, so the letters are laid out by
  sound on a QWERTY keyboard: `q` is `ق`, `t` is `ت`, `s` is `س`, and a key's kin is on shift
  (`ت` and, shifted, `ٹ`; `د` and `ڈ`; `ر` and `ڑ`; `ہ` and `ھ`; `ا` and `آ`; `ء` and `ئ`).
- Every letter of the Urdu alphabet, the signs (zabar, zer, pesh, shadda, jazm, khari zabar,
  maddah, hamza above) and the Urdu comma, full stop, question mark and semicolon are on a key.
- The row of digits is Urdu (`۱–۰`, which are not the Arabic ones for 4, 5 and 6), and ASCII (`1–0`)
  with shift, since documents hold both. The numbers and symbols layer has the ASCII digits.
- The keys sit where the physical keys are, left to right, though Urdu reads right to left.
- The layout is data (`LAYERS` in `src/layout.js`).
