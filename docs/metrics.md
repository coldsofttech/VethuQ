# Anonymous usage statistics

VethuQ can share anonymous statistics about how it is used, to find out where reading and search
can be better. **It is off unless you turn it on.** You see exactly what would be sent first, you
can turn it off at any time, and you can have what was sent deleted.

## What is sent

One batch a day, of closed UTC days, over https, to the address in VethuQ's signed policy. It is
counts, timings and buckets, listed in full in `metrics/schema/v1/batch.schema.json` (anything not
listed is refused by the collector and never leaves your computer):

- **About your install:** the VethuQ version, Python version, operating system and architecture,
  CPU and memory in buckets (for example "5-8 cores", "16 GB"), and a few settings (workers, retries,
  default languages, confidence bands).
- **Reading:** per file type, phase, language, engine, page source and page-size bucket: how many
  pages and passes, how long they took, the sum of confidences (for the average and the share of low
  confidence), the credits charged, and a count of failures by reason code (for example `password`).
- **Events:** how often a run stopped for lack of credits, and, for searches, the engine, the number of
  words of the query (1, 2-3, 4-8, 9+), its script (Latin, Telugu, mixed, other), the number of
  results (0, 1-9, 10-99, 100+) and how long it took (under 50 ms, 200 ms, 1 s, more).
- **A random install id**, made on your computer, not derived from the computer, user, licence or
  GitHub account. It exists so your data can be deleted on request.

## What is never sent

File names, folder paths, document text, OCR text, the text of a search, user names, GitHub ids,
licence ids, device hashes, IP addresses (the collector stores none, though the hosting provider's
network sees one in order to answer). Native-text pages and the GitHub tier add nothing more: the
worker in a runner repository never makes a network call, and its numbers reach the batch only
through your computer, and only if you opted in.

## Turning it on, looking, and turning it off

- The first time you use the desktop interface it asks once; "Not now" asks no more. Nothing is
  selected for you.
- `vethuq metrics status` says where it stands. `vethuq metrics preview` prints the batch that would
  be sent next, exactly as it would be sent. `vethuq metrics opt-in` and `opt-out` turn it on and
  off (the same toggle is in Settings and under Maintenance). Turning it off also drops what was
  waiting to be sent.
- `vethuq metrics rotate-id` makes a new random id, so what is sent from then on isn't linked to
  what was sent before.
- `vethuq metrics delete-data` asks the collector to delete everything it holds for your id and
  starts a new id.
- If what is shared grows (a new category is added), sharing pauses and the bonus stops until you
  agree again (`vethuq metrics opt-in`); `status` says so.
- Unsent days older than 30 days are dropped rather than sent late.

## The credits bonus

While sharing is on and a batch was sent in the last 7 days, your daily credits are 10% higher
(the signed policy sets the amount, capped at 15%), from the UTC day after a send. It is a thank-you,
not payment for data: it is small, and nothing else changes if you don't share.

## What the collector keeps

Daily totals per install (never per event), the install's hardware buckets and settings, and the
record of each batch (its id and time, to count a batch once) for 90 days. It accepts a few batches
an install a day, refuses a batch no computer could make, and the server code is public in
`metrics/collector`. Deletion by install id removes all of it; how requests are handled is in the
private fulfilment runbook.

## Legal basis

Consent, given by turning it on, and withdrawn by turning it off.
