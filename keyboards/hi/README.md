# @vethuq/keyboard-hi

An on-screen Hindi keyboard for VethuQ's search box: `@vethuq/keyboard-shared` with the Hindi
(Devanagari) layout. Like the viewers it lives outside `web/` and knows nothing about VethuQ or its
API; it reports the keys pressed and whoever uses it types into its own field.

```jsx
<HindiKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'क' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- The layout is InScript, the standard one: vowel signs and vowels on the left, consonants on the
  right, a vowel sign on a key and its vowel on the same key with shift (`ा` and, shifted, `आ`).
  The nukta `़`, the candra sign `ॉ` (and `ऑ`, as in `डॉक्टर`) and the rarer letters are on it too, and
  the danda `।` is by the full stop.
- The row of digits is Devanagari (`१–०`) as on InScript, and ASCII (`1–0`) with shift, since
  documents hold both. The numbers and symbols layer has the ASCII digits.
- The layout is data (`LAYERS` in `src/layout.js`).
