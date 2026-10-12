import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { strings } from '../strings.js';

/** @type {import('../api/client.js').Brand} */
const FALLBACK = { name: strings.appName, tagline: strings.tagline, palette: null };

const BrandContext = createContext(FALLBACK);

/**
 * Loads the app's name, tagline and colour palette from the core before anything is drawn, so the
 * first paint already has the right colours. If the service cannot be reached the interface still
 * renders, with the built-in names and the stock Fluent colours.
 */
export function BrandProvider({ children }) {
  const [brand, setBrand] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    api.brand(controller.signal).then(
      (loaded) => setBrand(loaded),
      (error) => {
        if (error?.name !== 'AbortError') setBrand(FALLBACK);
      },
    );
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (brand) document.title = brand.name;
  }, [brand]);

  if (!brand) return null;
  return <BrandContext.Provider value={brand}>{children}</BrandContext.Provider>;
}

export function useBrand() {
  return useContext(BrandContext);
}
