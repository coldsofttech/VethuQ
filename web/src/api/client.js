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
 * @property {'boolean' | 'integer' | 'number' | 'choice' | 'multichoice' | 'bands'} type
 * @property {string | number | boolean | Array<string | number>} value
 * @property {string | number | boolean | Array<string | number>} default
 * @property {boolean} is_default
 * @property {boolean} advanced
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

export const api = {
  /** @returns {Promise<{ status: string }>} */
  health: (signal) => request('/api/health', { signal }),
  /** @returns {Promise<AboutDetails>} */
  about: (signal) => request('/api/about', { signal }),
  settings: {
    /** @param {string} section @returns {Promise<{ section: string, settings: Setting[] }>} */
    list: (section, signal) => request(`/api/settings/${section}`, { signal }),
    /** @param {string} section @param {string} id @param {unknown} value @returns {Promise<Setting>} */
    update: (section, id, value) =>
      request(`/api/settings/${section}/${id}`, { method: 'PUT', body: { value } }),
    /** @param {string} section @param {string} id @returns {Promise<Setting>} */
    reset: (section, id) => request(`/api/settings/${section}/${id}`, { method: 'DELETE' }),
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
