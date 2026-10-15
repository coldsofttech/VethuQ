/** Logs: a line tokenizer. Every line is coloured on its own. */
import { collector, highlighterFor } from './highlighter.js';

const TOKEN = new RegExp(
  [
    String.raw`(?<time>\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[-+]\d\d:?\d\d)?|\d\d:\d\d:\d\d(?:[.,]\d+)?)`,
    String.raw`(?<level>\b(?:ERROR|FATAL|CRITICAL|SEVERE|WARN(?:ING)?|INFO|NOTICE|DEBUG|TRACE)\b)`,
    String.raw`(?<bracket>\[[^\]\n]*\])`,
    String.raw`(?<string>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')`,
    String.raw`(?<pair>\b[\w.-]+(?==))`,
    String.raw`(?<number>\b\d+(?:\.\d+)?\b)`,
  ].join('|'),
  'g',
);

const LEVEL = (word) =>
  /^(ERROR|FATAL|CRITICAL|SEVERE)$/.test(word)
    ? 'regexp'
    : /^WARN/.test(word)
      ? 'selector'
      : /^(DEBUG|TRACE)$/.test(word)
        ? 'comment'
        : 'storage';

/** Colours one line. State-free: `from` and the returned `state` are always `null`. */
export function scan(line, from, collect = true) {
  const { segments, push } = collector(collect);
  let at = 0;
  for (const found of line.matchAll(TOKEN)) {
    push(null, line.slice(at, found.index));
    const [kind] = Object.entries(found.groups).find(([, value]) => value !== undefined);
    push(
      kind === 'time'
        ? 'number'
        : kind === 'level'
          ? LEVEL(found[0])
          : kind === 'bracket'
            ? 'identifier'
            : kind === 'pair'
              ? 'key'
              : kind === 'string'
                ? 'string'
                : 'number',
      found[0],
    );
    at = found.index + found[0].length;
  }
  push(null, line.slice(at));
  return { segments, state: null };
}

export const LogHighlighter = highlighterFor(null, scan);
