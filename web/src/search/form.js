/** What the search bar holds, and how it becomes a request. */

export const EMPTY_FORM = {
  query: '',
  engine: '', // '' is the default engine of Settings
  caseSensitive: false,
  fileTypes: [],
  sources: [],
  languages: [],
  normalize: {}, // normalizer id -> level; missing means the saved level
  options: {}, // engine id -> { option: value }
  combine: '',
  sort: '',
  context: '',
};

/** The body of a search request; blank choices are left out so the Settings defaults apply. */
export function toRequest(form) {
  const body = { query: form.query.trim() };
  if (form.engine) body.engine = form.engine;
  if (form.caseSensitive) body.case_sensitive = true;
  if (form.fileTypes.length) body.file_types = form.fileTypes;
  if (form.sources.length) body.sources = form.sources.map(Number);
  if (form.languages.length) body.languages = form.languages;
  const normalize = Object.fromEntries(Object.entries(form.normalize).filter(([, level]) => level));
  if (Object.keys(normalize).length) body.normalize = normalize;
  const options = {};
  for (const [engine, values] of Object.entries(form.options)) {
    const set = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ''));
    if (Object.keys(set).length) options[engine] = set;
  }
  if (Object.keys(options).length) body.options = options;
  if (form.combine) body.combine = form.combine;
  if (form.sort) body.sort = form.sort;
  if (form.context !== '' && Number.isInteger(Number(form.context)))
    body.context_chars = Number(form.context);
  return body;
}

const KEY = 'vethuq.recent-searches';

/** The last searches typed, newest first, kept in this browser only. */
export function recentSearches() {
  try {
    const found = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(found) ? found.filter((q) => typeof q === 'string') : [];
  } catch {
    return [];
  }
}

export function rememberSearch(query) {
  const text = query.trim();
  if (!text) return recentSearches();
  const next = [text, ...recentSearches().filter((q) => q !== text)].slice(0, 10);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Not kept; the list still works for this visit.
  }
  return next;
}

export function forgetSearches() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to forget.
  }
}

/**
 * Where in the file a match sits, as the native application can be asked to jump to it.
 * @param {{file_type?: string | null, page_number?: number, line?: number | null, column?: number | null}} match
 * @returns {{page?: number, line?: number, column?: number}}
 */
export const placeOf = (match) => {
  if (match.file_type === 'pdf' && match.page_number) return { page: match.page_number };
  // A file the index keeps in another shape (Markdown without its markup, a stylesheet re-flowed,
  // JSON, YAML and XML as `path: value` lines, a Parquet table as its column names and rows, a script without blank lines) has no line that is
  // the file's own, and a CSV's or TSV's line is its Nth row with something in it: none is a line to open an
  // editor at.
  if (
    [
      'markdown',
      'css',
      'html',
      'json',
      'yaml',
      'toml',
      'js',
      'xml',
      'rss',
      'parquet',
      'ndjson',
      'mhtml',
      'svg',
    ].includes(match.file_type)
  )
    return {};
  // A picture's text was read by OCR: there is no line to open it at (a TIFF's frame is its page).
  if (['png', 'jpg', 'bmp', 'gif', 'webp', 'heic', 'jp2'].includes(match.file_type)) return {};
  if (['csv', 'tsv'].includes(match.file_type))
    return match.line != null ? { line: match.line } : {};
  if (match.line != null) {
    return match.column != null ? { line: match.line, column: match.column } : { line: match.line };
  }
  return {};
};

/** @param {{page?: number, line?: number, column?: number}} place */
export const describePlace = (place) => {
  if (place.page) return `Opens at page ${place.page}`;
  if (place.line) return `Opens at line ${place.line}`;
  return null;
};

/** The file types the preview can show: PDF, text, Markdown, CSV, TSV, Parquet, CSS, HTML, MHTML, JSON, NDJSON, YAML, JS, XML and pictures. */
export const canPreview = (match) =>
  [
    'pdf',
    'txt',
    'markdown',
    'csv',
    'tsv',
    'parquet',
    'css',
    'html',
    'mhtml',
    'json',
    'ndjson',
    'yaml',
    'toml',
    'js',
    'xml',
    'rss',
    'png',
    'jpg',
    'tiff',
    'bmp',
    'gif',
    'webp',
    'heic',
    'jp2',
    'svg',
  ].includes(match.file_type);
