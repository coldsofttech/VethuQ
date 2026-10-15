import {
  CSharpHighlighter,
  CssHighlighter,
  GoHighlighter,
  JsHighlighter,
  IniHighlighter,
  JavaHighlighter,
  JsonHighlighter,
  LogHighlighter,
  PhpHighlighter,
  PowerShellHighlighter,
  PythonHighlighter,
  RubyHighlighter,
  RustHighlighter,
  RstHighlighter,
  ShellHighlighter,
  SqlHighlighter,
  TomlHighlighter,
  XmlHighlighter,
  YamlHighlighter,
  formatCss,
  formatJs,
  formatJson,
  formatXml,
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
  css: {
    label: 'CSS',
    Highlighter: CssHighlighter,
    format: formatCss,
    hint: () => null,
  },
  js: {
    label: 'JavaScript',
    Highlighter: JsHighlighter,
    format: formatJs,
    hint: () => null,
  },
  json: {
    label: 'JSON',
    Highlighter: JsonHighlighter,
    format: formatJson,
    hint: (before) => {
      const key = keyBefore(before);
      return key ? `"${key}"` : null;
    },
  },
  // One JSON value to a line, so the JSON colouring (which takes a line on its own) fits; there
  // is no layout, because a minified line is a record and the file is readable as it is.
  ndjson: {
    label: 'NDJSON',
    Highlighter: JsonHighlighter,
    format: null,
    hint: (before) => {
      const key = keyBefore(before);
      return key ? `"${key}"` : null;
    },
  },
  ini: { label: 'INI', Highlighter: IniHighlighter, format: null, hint: keyBefore },
  sql: { label: 'SQL', Highlighter: SqlHighlighter, format: null, hint: () => null },
  rst: { label: 'reStructuredText', Highlighter: RstHighlighter, format: null, hint: () => null },
  py: { label: 'Python', Highlighter: PythonHighlighter, format: null, hint: () => null },
  java: { label: 'Java', Highlighter: JavaHighlighter, format: null, hint: () => null },
  ts: { label: 'TypeScript', Highlighter: JsHighlighter, format: null, hint: () => null },
  tsx: { label: 'TSX', Highlighter: JsHighlighter, format: null, hint: () => null },
  jsx: { label: 'JSX', Highlighter: JsHighlighter, format: null, hint: () => null },
  cs: { label: 'C#', Highlighter: CSharpHighlighter, format: null, hint: () => null },
  go: { label: 'Go', Highlighter: GoHighlighter, format: null, hint: () => null },
  rs: { label: 'Rust', Highlighter: RustHighlighter, format: null, hint: () => null },
  php: { label: 'PHP', Highlighter: PhpHighlighter, format: null, hint: () => null },
  rb: { label: 'Ruby', Highlighter: RubyHighlighter, format: null, hint: () => null },
  sh: { label: 'Shell', Highlighter: ShellHighlighter, format: null, hint: () => null },
  ps1: { label: 'PowerShell', Highlighter: PowerShellHighlighter, format: null, hint: () => null },
  // A notebook is JSON, already laid out; the index holds its cells, so there is no key to look under.
  ipynb: { label: 'Notebook', Highlighter: JsonHighlighter, format: null, hint: () => null },
  log: { label: 'Log', Highlighter: LogHighlighter, format: null, hint: () => null },
  toml: {
    label: 'TOML',
    Highlighter: TomlHighlighter,
    format: null,
    hint: keyBefore,
  },
  yaml: {
    label: 'YAML',
    Highlighter: YamlHighlighter,
    format: null,
    hint: keyBefore,
  },
  xml: {
    label: 'XML',
    Highlighter: XmlHighlighter,
    format: formatXml,
    hint: keyBefore,
  },
};
