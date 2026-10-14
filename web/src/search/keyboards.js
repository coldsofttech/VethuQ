import { EnglishKeyboard } from '@vethuq/keyboard-en';
import { HindiKeyboard } from '@vethuq/keyboard-hi';
import { TeluguKeyboard } from '@vethuq/keyboard-te';
import { UrduKeyboard } from '@vethuq/keyboard-ur';

/** The on-screen keyboards the search box offers, the first being the one used until another is picked. */
export const KEYBOARDS = [
  { id: 'en', label: 'English', Component: EnglishKeyboard },
  { id: 'hi', label: 'हिन्दी (Hindi)', Component: HindiKeyboard },
  { id: 'te', label: 'తెలుగు (Telugu)', Component: TeluguKeyboard },
  { id: 'ur', label: 'اردو (Urdu)', Component: UrduKeyboard },
];

const KEY = 'vethuq.keyboard-language';

/** The id of the keyboard picked last, kept in this browser only. */
export function savedKeyboard() {
  try {
    const id = localStorage.getItem(KEY);
    return KEYBOARDS.some((k) => k.id === id) ? id : KEYBOARDS[0].id;
  } catch {
    return KEYBOARDS[0].id;
  }
}

export function saveKeyboard(id) {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // Not kept; it still applies for this visit.
  }
}
