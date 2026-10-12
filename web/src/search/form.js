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
