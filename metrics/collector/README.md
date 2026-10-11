# VethuQ metrics collector

Receives the anonymous usage metrics VethuQ users **opt in** to share (see `docs/credits.md`,
section 7.1, and `client.metrics` in the `VethuQ` package). A [Cloudflare Worker](https://developers.cloudflare.com/workers/)
with a [D1](https://developers.cloudflare.com/d1/) database. It is public on purpose: so is the
[schema](../schema/v1/batch.schema.json) it enforces.

| Route | Does |
|---|---|
| `POST /v1/batch` | validates a batch against the schema (anything extra is refused) and adds it to the daily totals; a batch sent twice counts once |
| `POST /v1/delete` | `{"install_id": "…"}`: deletes everything held for that install |
| `GET /v1/health` | liveness |

What is stored: per install a random id, rough hardware buckets and the settings used; per day,
page counts, timings, confidence sums, credits, and failure counts by reason code. No file names,
paths, content, OCR text, search text, user names, licence ids or device hashes.

## Test

```bash
cd metrics/collector
npm ci
npm test        # uses node:sqlite for the real SQL; needs Node 22.5+
```

## Deploy

Use the **Deploy metrics collector** workflow (`.github/workflows/deploy-collector.yml`), or by hand:

```bash
npx wrangler login
npx wrangler d1 create vethuq-metrics        # once; put the database_id in wrangler.toml
npm run migrate
npm run deploy
```

The workflow needs two repository (or environment) secrets: `CLOUDFLARE_API_TOKEN` (a token with
*Workers Scripts: Edit* and *D1: Edit*) and `CLOUDFLARE_ACCOUNT_ID`. Then publish the Worker's URL
as `metrics.endpoint` in the signed policy (the base URL, without `/v1/batch`), and keep
`metrics.max_batch_bytes` at or under `MAX_BODY_BYTES` in `wrangler.toml`.
