import {
  TextViewer,
  locateWords,
  vscodeDark,
  vscodeLight,
} from "@vethuq/text-viewer";
import { useCallback, useEffect, useMemo } from "react";
import { LANGUAGES } from "./languages.js";

// A file bigger than this is not laid out (that would be a lot of text to make): its source is shown.
const FORMAT_LIMIT = 20 * 1024 * 1024;
// A line longer than this is not drawn in full (nor coloured): a minified file is one such line.
const LONG_LINE = 20000;
// A file with a line this long is shown laid out (when its language can be) until told otherwise.
const MINIFIED = 2000;

/**
 * How a file is shown: `source` as it is, or `formatted` (laid out, for a minified file). The
 * choice is the person's (`null` until they make one); without it a file with a very long line
 * opens laid out, when its language has a layout.
 *
 * @param {string} language A key of `LANGUAGES`.
 * @param {string | null} text The file's text (null while it is being read).
 * @param {number} longestLine The length of its longest line.
 * @param {'source' | 'formatted' | null} choice
 * @returns {{mode: 'source' | 'formatted', canFormat: boolean, tooBig: boolean}}
 */
export function codeMode(language, text, longestLine, choice) {
  const tooBig = text !== null && text.length > FORMAT_LIMIT;
  const canFormat = Boolean(LANGUAGES[language]?.format) && !tooBig;
  const mode = !canFormat
    ? "source"
    : (choice ?? (longestLine > MINIFIED ? "formatted" : "source"));
  return { mode, canFormat, tooBig };
}

/**
 * A read-only view of a source file as Visual Studio Code would show it: line numbers and the colours
 * of its Dark+ or Light+ theme, only the lines in view in the page. The match is found in the text
 * shown by its words (and under its key, for a file indexed as `key: value` lines) and marked on its
 * line.
 *
 * @param {object} props
 * @param {string} props.text The file's text.
 * @param {string} props.language A key of `LANGUAGES` (`css`, `js`, `json`, `ndjson`, `yaml`, `toml`, `xml`).
 * @param {'source' | 'formatted'} [props.mode] Which text to show (see `codeMode`).
 * @param {{before?: string, matched?: string, after?: string} | null} [props.match] The words to find.
 * @param {boolean} [props.dark] Dark+ colours instead of Light+.
 * @param {(where: {line: number, column: number, offset: number, end: number} | null) => void} [props.onLocated]
 *   Called with where the match is in the text shown (1-based line), or null if it is not there.
 */
export function CodeViewer({
  text,
  language,
  mode = "source",
  match = null,
  dark = false,
  onLocated,
}) {
  const spec = LANGUAGES[language];
  const shown = useMemo(
    () => (mode === "formatted" && spec.format ? spec.format(text) : text),
    [text, mode, spec],
  );
  const lines = useMemo(() => shown.split("\n"), [shown]);
  const highlighter = useMemo(() => new spec.Highlighter(lines), [lines, spec]);
  const colour = useCallback(
    (_, line) =>
      lines[line].length > LONG_LINE ? null : highlighter.segments(line),
    [lines, highlighter],
  );
  const loadLines = useCallback(
    (start, count) =>
      Promise.resolve(
        lines
          .slice(start, start + count)
          .map((l) => (l.length > LONG_LINE ? `${l.slice(0, LONG_LINE)}…` : l)),
      ),
    [lines],
  );

  const before = match?.before;
  const matched = match?.matched;
  const after = match?.after;
  const where = useMemo(
    () =>
      matched === undefined || matched === null
        ? null
        : locateWords(shown, {
            before,
            matched,
            after,
            hint: spec.hint(before) ?? undefined,
          }),
    [shown, before, matched, after, spec],
  );
  useEffect(() => {
    onLocated?.(where);
  }, [where, onLocated]);

  const target = useMemo(
    () =>
      where
        ? {
            line: where.line,
            column: where.column,
            length: where.end - where.offset,
          }
        : undefined,
    [where],
  );

  return (
    <TextViewer
      key={`${language}:${mode}`}
      total={lines.length}
      loadLines={loadLines}
      tokens={colour}
      theme={dark ? vscodeDark : vscodeLight}
      target={target}
      label={`${spec.label} source`}
    />
  );
}
