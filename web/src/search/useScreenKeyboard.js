import { useCallback, useLayoutEffect, useRef } from 'react';

/**
 * Types the keys of an on-screen keyboard into a controlled text field: at the caret, over the
 * selection, with the caret put back after React has drawn the new value.
 *
 * @param {React.RefObject<HTMLInputElement>} inputRef the field
 * @param {string} value what the field holds
 * @param {(value: string) => void} setValue
 * @param {() => void} onEnter
 */
export function useScreenKeyboard(inputRef, value, setValue, onEnter) {
  const caret = useRef(null);

  useLayoutEffect(() => {
    if (caret.current === null) return;
    inputRef.current?.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  }, [inputRef, value]);

  return useCallback(
    (key) => {
      if (key.type === 'enter') return onEnter();
      const input = inputRef.current;
      const text = input?.value ?? value;
      const start = input?.selectionStart ?? text.length;
      const end = input?.selectionEnd ?? text.length;
      let next;
      if (key.type === 'backspace') {
        const from = start === end ? Math.max(0, start - 1) : start;
        next = { text: text.slice(0, from) + text.slice(end), at: from };
      } else {
        next = {
          text: text.slice(0, start) + key.value + text.slice(end),
          at: start + key.value.length,
        };
      }
      caret.current = next.at;
      setValue(next.text);
    },
    [inputRef, value, setValue, onEnter],
  );
}
