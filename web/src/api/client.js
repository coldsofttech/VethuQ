/**
 * @typedef {object} AboutDetails
 * @property {string} vethuq
 * @property {string} python
 * @property {string} platform
 * @property {number} db_schema
 *
 * @typedef {Record<string, string>} PaletteScheme  Design tokens by name, as "#RRGGBB".
 *
 * @typedef {object} Brand
 * @property {string} name
 * @property {string} tagline
 * @property {{ light: PaletteScheme, dark: PaletteScheme }} palette
 *
 * @typedef {object} SettingOption
 * @property {string | number | boolean} value
 * @property {string} label
 * @property {boolean} available
 * @property {string} reason
 *
 * @typedef {object} Setting  One setting, described by the API.
 * @property {string} id
 * @property {string} label
 * @property {string} description
 * @property {'boolean' | 'integer' | 'number' | 'choice' | 'multichoice' | 'bands' | 'text' | 'path'} type
 * @property {string | number | boolean | Array<string | number> | null} value
 * @property {string | number | boolean | Array<string | number>} default
 * @property {boolean} is_default
 * @property {boolean} advanced
 * @property {boolean} [readonly]  Shown but not editable; reset clears it.
 * @property {string} [locked]  Why it cannot be changed now (for example an environment variable), or ''.
 * @property {string} [group]  A heading the screen puts above a run of related settings.
 * @property {string} [group_note]
 * @property {boolean} [resettable]  False when there is nothing to reset to.
 * @property {boolean} [can_move]  Changing it can move data (the data folder).
 * @property {string} note  When the change takes effect, or ''.
 * @property {SettingOption[]} [options]  For a choice or multichoice.
 * @property {string[]} [labels]  The names of the three fields of `bands`.
 * @property {number} [min]
 * @property {number} [max]
 * @property {string} [unit]
 *
 * @typedef {object} SourceRow
 * @property {number} id
 * @property {string} path
 * @property {string} name
 * @property {string} parent
 * @property {'file' | 'folder'} type
 * @property {string} status
 * @property {string[] | null} languages
 * @property {string} added_at
 * @property {string | null} last_scanned_at
 * @property {string | null} removed_at
 * @property {boolean} active
 * @property {number} files_total
 * @property {number} files_processed
 * @property {boolean} missing  The path is no longer on disk.
 *
 * @typedef {object} FileRow
 * @property {string} path
 * @property {string} relative_path
 * @property {string} name
 * @property {number} size_bytes
 * @property {string} modified_at
 * @property {string | null} status
 * @property {string | null} file_type  Null when no add-on reads this kind of file.
 * @property {boolean} protected  A known kind of file that needs a password.
 * @property {string | null} [error]
 * @property {number | null} [pages]
 * @property {number | null} [confidence]
 * @property {string | null} [band]
 * @property {string[] | null} [languages]
 *
 * @typedef {object} IndexState
 * @property {object | null} run
 * @property {boolean} active
 * @property {boolean} paused
 * @property {boolean} stopping
 * @property {boolean} stalled
 * @property {object | null} eta
 * @property {string[]} current_files
 * @property {number} remote_jobs_open
 * @property {number} queued
 * @property {{ mode: 'idle' | 'one-off' | 'service' | 'external', service_running: boolean }} runner
 * @property {string | null} error
 * @property {{ colour: string, label: string, tooltip: string, state: string } | null} service
 *
 * @typedef {object} CatalogAddon
 * @property {string} id
 * @property {string} name
 * @property {string} version
 * @property {string} status
 * @property {string} detail
 *
 * @typedef {object} CatalogItem  A file type, search engine, language or OCR engine.
 * @property {string} id
 * @property {string} label
 * @property {boolean} available
 * @property {string} reason
 * @property {string[]} [extensions]
 * @property {string} [description]
 * @property {string} [native_label]
 * @property {boolean} [enabled]
 * @property {string[]} [profiles]
 *
 * @typedef {object} Catalog
 * @property {CatalogAddon[]} add_ons
 * @property {CatalogItem[]} file_types
 * @property {CatalogItem[]} search_engines
 * @property {CatalogItem[]} languages
 * @property {CatalogItem[]} ocr_engines
 *
 * @typedef {object} PlatformInfo
 * @property {'desktop' | 'web'} kind
 * @property {boolean} window_controls  Whether the host window can be minimised/maximised/closed.
 * @property {boolean} folder_dialog  Whether the host can show a folder picker.
 * @property {boolean} file_dialog  Whether the host can show a file picker.
 * @property {boolean} reveal  Whether the host can show a file in its folder.
 *
 * @typedef {object} WindowState
 * @property {boolean} maximized
 */

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} status HTTP status, or 0 when the service could not be reached.
   */
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Calls the Flask API on the same origin. The session cookie is set by the host application.
 * @template T
 * @param {string} path
 * @param {{ method?: string, body?: unknown, signal?: AbortSignal }} [options]
 * @returns {Promise<T>}
 */
/** A query string from the values that are set (empty ones are left out). */
export function query(params) {
  const pairs = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '' && v !== false,
  );
  if (pairs.length === 0) return '';
  return `?${new URLSearchParams(pairs.map(([k, v]) => [k, v === true ? '1' : String(v)])).toString()}`;
}

export async function request(path, { method = 'GET', body, signal } = {}) {
  /** @type {RequestInit} */
  const init = {
    method,
    signal,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('The service is not reachable', 0);
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      if (payload && typeof payload.error === 'string') message = payload.error;
    } catch {
      // The body was not JSON; keep the status text.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return /** @type {T} */ (undefined);
  return /** @type {Promise<T>} */ (response.json());
}

/**
 * Like `request`, for an endpoint that answers with plain text.
 * @param {string} path
 * @returns {Promise<string>}
 */
export async function requestText(path) {
  let response;
  try {
    response = await fetch(path, { credentials: 'same-origin' });
  } catch {
    throw new ApiError('The service is not reachable', 0);
  }
  if (!response.ok) throw new ApiError(response.statusText, response.status);
  return response.text();
}

export const api = {
  /** @returns {Promise<{ status: string }>} */
  health: (signal) => request('/api/health', { signal }),
  /** @returns {Promise<AboutDetails>} */
  about: (signal) => request('/api/about', { signal }),
  sources: {
    /** @param {Record<string, string | boolean>} [filters] @returns {Promise<{ sources: SourceRow[] }>} */
    list: (filters = {}, signal) => request(`/api/sources${query(filters)}`, { signal }),
    /** @returns {Promise<SourceRow>} */
    get: (id, signal) => request(`/api/sources/${id}`, { signal }),
    /** @returns {Promise<SourceRow>} */
    add: (path, languages) =>
      request('/api/sources', { method: 'POST', body: { path, languages } }),
    remove: (id) => request(`/api/sources/${id}`, { method: 'DELETE' }),
    restore: (id) => request(`/api/sources/${id}/restore`, { method: 'POST' }),
    purge: (id) => request(`/api/sources/${id}/purge`, { method: 'POST' }),
    setLanguages: (id, languages) =>
      request(`/api/sources/${id}/languages`, { method: 'PUT', body: { languages } }),
    /** @returns {Promise<{ total: number, all: number, items: FileRow[], facets: { status: Record<string, number>, type: Record<string, number> } }>} */
    files: (id, params = {}, signal) =>
      request(`/api/sources/${id}/files${query(params)}`, { signal }),
    exportUrl: (format, params = {}) => `/api/sources/export${query({ format, ...params })}`,
    filesExportUrl: (id, format, params = {}) =>
      `/api/sources/${id}/files/export${query({ format, ...params })}`,
  },
  index: {
    /** @returns {Promise<IndexState>} */
    state: (signal) => request('/api/index/state', { signal }),
    /** Collect finished remote results, then the state. @returns {Promise<IndexState>} */
    refresh: (signal) => request('/api/index/refresh', { method: 'POST', signal }),
    /** @param {'run' | 'restart' | 'reindex' | 'file'} mode @param {number | string | null} [target] */
    start: (mode, target = null) =>
      request('/api/index/start', { method: 'POST', body: { mode, target } }),
    pause: () => request('/api/index/pause', { method: 'POST' }),
    resume: () => request('/api/index/resume', { method: 'POST' }),
    stop: () => request('/api/index/stop', { method: 'POST' }),
    history: (params = {}, signal) => request(`/api/index/history${query(params)}`, { signal }),
    jobs: (signal) => request('/api/index/jobs', { signal }),
    requests: (signal) => request('/api/index/requests', { signal }),
    cancelRequest: (id) => request(`/api/index/requests/${id}/cancel`, { method: 'POST' }),
  },
  ocr: {
    /** @returns {Promise<{ engines: object[], phases: object[] }>} */
    overview: (signal) => request('/api/ocr', { signal }),
    models: (signal) => request('/api/ocr/models', { signal }),
    job: (signal) => request('/api/ocr/job', { signal }),
    /** @param {'download' | 'redownload'} action */
    start: (action, body = {}) => request(`/api/ocr/models/${action}`, { method: 'POST', body }),
    clear: (languages, includeShared) =>
      request('/api/ocr/models/clear', {
        method: 'POST',
        body: { languages, include_shared: includeShared },
      }),
    clean: () => request('/api/ocr/models/clean', { method: 'POST' }),
  },
  stats: {
    summary: (params = {}, signal) => request(`/api/stats/summary${query(params)}`, { signal }),
    breakdown: (params = {}, signal) => request(`/api/stats/breakdown${query(params)}`, { signal }),
    exportUrl: (format, params = {}) => `/api/stats/export${query({ format, ...params })}`,
  },
  credits: {
    summary: (signal) => request('/api/credits/summary', { signal }),
    wallets: (signal) => request('/api/credits/wallets', { signal }),
    grants: (params = {}, signal) => request(`/api/credits/grants${query(params)}`, { signal }),
    usage: (params = {}, signal) => request(`/api/credits/usage${query(params)}`, { signal }),
    daily: (days, signal) => request(`/api/credits/daily${query({ days })}`, { signal }),
    ledger: (params = {}, signal) => request(`/api/credits/ledger${query(params)}`, { signal }),
    exportUrl: (what, format, params = {}) =>
      `/api/credits/export/${what}${query({ format, ...params })}`,
    redeem: (token) => request('/api/credits/redeem', { method: 'POST', body: { token } }),
  },
  service: {
    /** @param {'start' | 'stop' | 'pause' | 'resume'} action */
    perform: (action) => request(`/api/service/${action}`, { method: 'POST' }),
  },
  os: {
    reveal: (path) => request('/api/os/reveal', { method: 'POST', body: { path } }),
  },
  settings: {
    /** @param {string} section @returns {Promise<{ section: string, settings: Setting[] }>} */
    list: (section, signal) => request(`/api/settings/${section}`, { signal }),
    /** @param {string} section @param {string} id @param {unknown} value @returns {Promise<Setting>} */
    update: (section, id, value, options) =>
      request(`/api/settings/${section}/${id}`, {
        method: 'PUT',
        body: options ? { value, options } : { value },
      }),
    /** @param {string} section @param {string} id @param {{ move?: boolean }} [options] @returns {Promise<Setting>} */
    reset: (section, id, options) =>
      request(`/api/settings/${section}/${id}`, {
        method: 'DELETE',
        body: options ? { options } : undefined,
      }),
  },
  /** The text to paste into a support request. @returns {Promise<string>} */
  supportInfo: () => requestText('/api/support-info'),
  dialog: {
    /** @param {string} [start] @returns {Promise<{ path: string | null }>} */
    folder: (start) => request('/api/dialog/folder', { method: 'POST', body: { start } }),
    /** @param {string} [start] @returns {Promise<{ path: string | null }>} */
    file: (start) => request('/api/dialog/file', { method: 'POST', body: { start } }),
  },
  /** @returns {Promise<Brand>} */
  brand: (signal) => request('/api/brand', { signal }),
  /** @returns {Promise<Catalog>} */
  catalog: (signal) => request('/api/catalog', { signal }),
  /** @returns {Promise<PlatformInfo>} */
  platform: (signal) => request('/api/platform', { signal }),
  window: {
    /** @returns {Promise<WindowState>} */
    state: () => request('/api/window/state'),
    /** @param {'minimize' | 'maximize' | 'restore' | 'close'} action @param {{ force?: boolean }} [body] */
    perform: (action, body) => request(`/api/window/${action}`, { method: 'POST', body }),
  },
};
