import {
  CssHighlighter,
  JsHighlighter,
  JsonHighlighter,
  XmlHighlighter,
  YamlHighlighter,
  formatCss,
  formatJs,
  formatJson,
  formatXml,
  locateWords,
} from '@vethuq/text-viewer';

/**
 * The key a match's value sits under, for a file the index flattened to `path: value` lines
 * (`server.ports[0]: 8080`, `catalog/book@id: 7`): the last name of the path, so the value can be
 * found under it. Nothing when the match is not a value.
 *
 * @param {string | undefined} before The text before the match.
 * @returns {string | null}
 */
export function keyBefore(before) {
  const path = /(\S+):\s*$/.exec(before ?? '')?.[1];
  if (!path) return null;
  const names = path.split(/[./@[\]]+/).filter((part) => part && !/^\d+$/.test(part));
  return names.at(-1) ?? null;
}

/**
 * What the code preview needs to know of each file type it shows: its name, how to colour it, how
 * to lay out a minified file (none: it is readable as written), and how to find a match in it.
 */
export const LANGUAGES = {
  css: { label: 'CSS', Highlighter: CssHighlighter, format: formatCss, hint: () => null },
  js: { label: 'JavaScript', Highlighter: JsHighlighter, format: formatJs, hint: () => null },
  json: {
    label: 'JSON',
    Highlighter: JsonHighlighter,
    format: formatJson,
    hint: (before) => {
      const key = keyBefore(before);
      return key ? `"${key}"` : null;
    },
  },
  yaml: { label: 'YAML', Highlighter: YamlHighlighter, format: null, hint: keyBefore },
  xml: { label: 'XML', Highlighter: XmlHighlighter, format: formatXml, hint: keyBefore },
};

export { locateWords };
