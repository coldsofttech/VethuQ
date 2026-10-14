# @vethuq/keyboard-te

An on-screen Telugu keyboard for VethuQ's search box: `@vethuq/keyboard-shared` with the Telugu
layout. Like the viewers it lives outside `web/` and knows nothing about VethuQ or its API; it
reports the keys pressed and whoever uses it types into its own field.

```jsx
<TeluguKeyboard
  onKey={(key) => ...}  // { type: 'text', value: 'క' } | { type: 'backspace' } | { type: 'enter' }
  onClose={() => ...}   // the hide key
/>
```

- The layout is InScript, the standard one: vowel signs and vowels on the left, consonants on the
  right, a vowel sign on a key and its vowel on the same key with shift (`ా` and, shifted, `ఆ`).
  Rarer letters and signs (`ఋ ౠ ఴ ఽ`) are on shift too. Every vowel, consonant and sign is on one key.
- The row of digits is Telugu (`౧–౦`) as on InScript, and ASCII (`1–0`) with shift, since documents
  hold both. The numbers and symbols layer has the ASCII digits.
- The layout is data (`LAYERS` in `src/layout.js`).
