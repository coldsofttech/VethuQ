/**
 * The number a Fluent SpinButton change stands for. Stepping reports `value`; a typed number is
 * reported once, when committed (Enter or leaving the field), with only its text (`displayValue`),
 * so the text is parsed here. Returns null for text that is not a number.
 *
 * @param {{ value?: number | null, displayValue?: string }} data
 * @returns {{ number: number | null }}
 */
export function readSpin(data) {
  if (typeof data.value === 'number' && Number.isFinite(data.value)) return { number: data.value };
  const text = (data.displayValue ?? '').trim();
  const parsed = Number(text);
  return { number: text !== '' && Number.isFinite(parsed) ? parsed : null };
}
