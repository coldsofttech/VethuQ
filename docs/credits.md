# Credits

Credits pay for OCR work. One credit is one A4 page read once on the fast model. This page is the
reference for the numbers; the signed policy can change any of them, from the next UTC day.

## 1. Wallets and allowances

| Wallet | Daily amount | Starter (once per device) |
|---|---|---|
| `local` | 500 | 2,000 |
| `github` | 20 with a private runner repository, 200 with a public one | none |
| add-on sub-wallets (`semantic`) | 50 local | none |

- The daily amount resets at 00:00 UTC and does not roll over. The clock never goes backwards.
- The GitHub amount follows the visibility the tier reports before each job. A change applies from
  the next UTC day; the day's grant is kept. `vethuq credits balance --wallet github` shows
  "20/day (private repository)".
- Sharing metrics adds up to 10% (cap 15%); a promotion adds its uplift (the highest one, capped at
  +100% of the daily amount); both are on top of the daily amount and end with their day.
- Spend order: promotion, daily, scoped one-off, general one-off, grace.
- Grace is 2% of the day's amount. A page that has started always finishes; then the run stops as
  `waiting_credits` and carries on after the reset.

## 2. What a page costs

`size factor = page area / A4 area`, reduced by 5%, rounded up to a quarter, at least 0.25, at most
16 (larger pages are refused). A page of an image file is taken to be 300 dpi, so its size is its
pixel count. Blank pages cost the minimum. Pages with native text, duplicates and unchanged files
cost nothing.

| Pass | Cost |
|---|---|
| quick, first language | `factor x 1.0 x device x fast` |
| another language | `factor x language_pass x device x fast` |
| each rotated pass (moderate, high) | `factor x 0.8 x device x advanced` |
| embedding a page (`semantic`) | 0.5, from the add-on's sub-wallet |

`device` is 1.0 for `cpu` and `gpu` until the policy says otherwise; a remote tier is CPU only.
Each ledger row has the device, the rate card version, the phase, the angle and the size factor.

### Model multipliers

`rate_card.model_multiplier.fast` is 1.0 and is the reference: the quick price never changes.
`rate_card.model_multiplier.advanced` multiplies the rotated passes of the moderate and high
phases, which run on the advanced model. The baseline is 1.0, so today a rotated pass costs 0.8 as
before (moderate +2.4, high +16.0 on an A4 page). The advanced model needs more compute per page;
set the multiplier in the policy once the benchmark is in, for example `advanced: 3.0` makes a
rotated pass 2.4 and moderate +7.2. Today's prices stay for the day in progress, and the new ones
apply from the next UTC day (the policy's rule for every rate).

### Images

Images are priced by size at 300 dpi, so a 150 dpi A4 scan (about 2 MP) is a quarter of an A4 page.
Measured time (benchmark #145) is close to flat below 200 dpi, so such a scan is read for roughly
three times what it is charged. This is left as it is for now: the GitHub wallet bounds the effect
(20 credits is at most 80 such pages a day), and the local wallet only uses the user's own computer.
A floor for page-like images (about A4 shape, over 1 MP) will be decided when the benchmark for
the advanced model is in, since #259 changes what a page costs anyway.

## 3. Asking for help

`vethuq credits report` (and `GET /api/credits/report`) prints balances, ledger totals per wallet
and kind, licence ids and statuses, and the versions. It has no file names, paths or document
content. The ledger is in the device folder (see `device-folder.md`), so `db backup`, `restore` and
`reset` do not touch it.
