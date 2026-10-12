/**
 * @typedef {object} AboutDetails
 * @property {string} vethuq
 * @property {string} python
 * @property {string} platform
 * @property {number} db_schema
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
