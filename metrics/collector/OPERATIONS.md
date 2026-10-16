# Running the collector

Nothing here is secret; the credentials live in the repository's settings.

## Watching it

Cloudflare's free plan allows 100,000 Worker requests a day, 100,000 D1 row writes a day and 5 GB of
D1 storage. A batch is about 5 + (rows in it) writes. In the Cloudflare dashboard set
**Notifications** for the Worker (error rate and "approaching usage limit") and for D1 (storage) at
**50%** and **80%**, to the maintainer's address. What happens at the limit: Cloudflare answers
errors; clients keep their days (they are sent the next day), and nothing blocks anyone's work.

## What the Worker enforces

Schema, request size (`MAX_BODY_BYTES`), at most 3 batches per install per UTC day (429), plausibility
bounds (422, `reason` says which), an optional per-address limit (`IP_LIMITER`, see `wrangler.toml`),
and a daily job that removes batch records older than 90 days. The turn-off and the address
come from the signed policy (`metrics.enabled`, `metrics.endpoint`, `metrics.max_batch_bytes`):
publish a policy with `enabled: false` and clients stop sending within a day.

## Export

Run weekly (a scheduled job or by hand) and keep the file in private storage:

```sh
npx wrangler d1 export vethuq-metrics --remote --output metrics-$(date +%F).sql
```

## Abuse

- **One install floods:** its batches are already limited to 3 a day. To block it, add its id to a
  `blocked` table (`INSERT INTO blocked VALUES ('<id>')`) and refuse it in `addBatch` (one line); or
  delete its data with `/v1/delete`.
- **Bad data got in:** delete a day range for an install (`DELETE FROM usage WHERE install_id = ?
  AND day BETWEEN ? AND ?`, the same for `failures` and `events`).
- **Tighten limits:** change `LIMITS` in `src/index.js` and deploy; a policy change of
  `max_batch_bytes` needs `MAX_BODY_BYTES` to match.

## Moving to AWS

The contract is three routes (`POST /v1/batch`, `POST /v1/delete`, `GET /v1/health`) and the schema in
`../schema/v1`. A move is: API Gateway plus a Lambda that runs the same validation and writes the same
rows to DynamoDB or Aurora, the same limits, a TTL on batch records, and then a policy change to the
new `metrics.endpoint` (old clients follow the policy, so no client release is needed). Do it when the
free tier is outgrown or the AWS tier needs the account.

## Deploying

`.github/workflows/metrics-collector.yml` (run it by hand and tick "deploy"). New migrations are in
`migrations/` and run with `npm run migrate`.
