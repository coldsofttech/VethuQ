/** How the core's words for credits read on screen. */

export function walletLabel(wallet) {
  if (wallet === 'github') return 'GitHub';
  return wallet ? wallet.charAt(0).toUpperCase() + wallet.slice(1) : '—';
}

export const KIND_LABELS = {
  daily: 'Daily allowance',
  promo: 'Promotion',
  one_off: 'One-off',
};

export const ENTRY_LABELS = {
  grant: 'Granted',
  charge: 'Charged',
  refund: 'Refunded',
  expire: 'Lapsed',
};

/** The signed amount of a ledger entry: spending shows as a minus. */
export function signedAmount(entry) {
  return entry.kind === 'charge' || entry.kind === 'expire' ? -entry.amount : entry.amount;
}

export const RANGES = [
  { value: '', label: 'All time' },
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
];

/** The ISO start of a "last N days" range, or undefined for all time. */
export function sinceOf(range) {
  if (!range) return undefined;
  const start = new Date(Date.now() - Number(range) * 86400000);
  return start.toISOString().slice(0, 10);
}
