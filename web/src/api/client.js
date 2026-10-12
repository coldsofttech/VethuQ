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
    /** @param {'minimize' | 'maximize' | 'restore' | 'close'} action @returns {Promise<WindowState>} */
    perform: (action) => request(`/api/window/${action}`, { method: 'POST' }),
  },
};
