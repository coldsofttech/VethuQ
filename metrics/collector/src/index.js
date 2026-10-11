// The VethuQ metrics collector: a Cloudflare Worker with a D1 database.
//
//   POST /v1/batch    a metrics batch (schema/v1/batch.schema.json), added to the daily totals
//   POST /v1/delete   {"install_id": "..."}: delete everything held for that install
//   GET  /v1/health   liveness
//
// Anything that does not match the schema exactly is refused, so no free text, path or other
// identifying field can be stored. Request bodies are never logged.

import { Validator } from "@cfworker/json-schema";
import batchSchema from "../../schema/v1/batch.schema.json" with { type: "json" };
import deleteSchema from "../../schema/v1/delete.schema.json" with { type: "json" };

const batchValidator = new Validator(batchSchema, "2020-12", false);
const deleteValidator = new Validator(deleteSchema, "2020-12", false);

const JSON_HEADERS = { "content-type": "application/json", "cache-control": "no-store" };

function reply(status, body) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function readJson(request, limit) {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > limit) return { error: reply(413, { error: "too large" }) };
  const text = await request.text();
  if (new TextEncoder().encode(text).length > limit) {
    return { error: reply(413, { error: "too large" }) };
  }
  try {
    return { value: JSON.parse(text) };
  } catch {
    return { error: reply(400, { error: "not json" }) };
  }
}

function problems(validator, value) {
  const result = validator.validate(value);
  return result.valid ? null : result.errors.slice(0, 5).map((e) => `${e.instanceLocation}: ${e.error}`);
}

export async function addBatch(db, batch, now = new Date()) {
  const received = now.toISOString();
  const seen = await db
    .prepare("INSERT OR IGNORE INTO batches (batch_id, install_id, received_at) VALUES (?, ?, ?)")
    .bind(batch.batch_id, batch.install_id, received)
    .run();
  if (!seen.meta.changes) return { status: "duplicate" };

  const c = batch.client;
  const s = batch.settings;
  const statements = [
    db
      .prepare(
        `INSERT INTO installs (install_id, first_seen, last_seen, vethuq, python, os, arch,
           cpu_bucket, ram_bucket, workers, retry_attempts, languages, confidence_bands)
         VALUES (?1, ?2, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
         ON CONFLICT (install_id) DO UPDATE SET last_seen = ?2, vethuq = ?3, python = ?4, os = ?5,
           arch = ?6, cpu_bucket = ?7, ram_bucket = ?8, workers = ?9, retry_attempts = ?10,
           languages = ?11, confidence_bands = ?12`,
      )
      .bind(
        batch.install_id, received, c.vethuq, c.python, c.os, c.arch, c.cpu_bucket, c.ram_bucket,
        String(s.workers), s.retry_attempts, s.languages.join(","), s.confidence_bands.join(","),
      ),
  ];
  for (const day of batch.days) {
    for (const p of day.pages) {
      statements.push(
        db
          .prepare(
            `INSERT INTO usage (install_id, day, file_type, phase, language, engine, page_source,
               size_bucket, band, pages, passes, duration_ms, confidence_sum, credits_milli)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT (install_id, day, file_type, phase, language, engine, page_source,
               size_bucket, band) DO UPDATE SET pages = pages + excluded.pages,
               passes = passes + excluded.passes, duration_ms = duration_ms + excluded.duration_ms,
               confidence_sum = confidence_sum + excluded.confidence_sum,
               credits_milli = credits_milli + excluded.credits_milli`,
          )
          .bind(
            batch.install_id, day.day, p.file_type, p.phase, p.language, p.engine, p.page_source,
            p.size_bucket, p.band, p.pages, p.passes, p.duration_ms, p.confidence_sum,
            p.credits_milli,
          ),
      );
    }
    for (const f of day.failures) {
      statements.push(
        db
          .prepare(
            `INSERT INTO failures (install_id, day, file_type, code, count) VALUES (?, ?, ?, ?, ?)
             ON CONFLICT (install_id, day, file_type, code) DO UPDATE SET count = count + excluded.count`,
          )
          .bind(batch.install_id, day.day, f.file_type, f.code, f.count),
      );
    }
  }
  await db.batch(statements);
  return { status: "ok", days: batch.days.length };
}

export async function deleteInstall(db, installId) {
  await db.batch([
    db.prepare("DELETE FROM usage WHERE install_id = ?").bind(installId),
    db.prepare("DELETE FROM failures WHERE install_id = ?").bind(installId),
    db.prepare("DELETE FROM batches WHERE install_id = ?").bind(installId),
    db.prepare("DELETE FROM installs WHERE install_id = ?").bind(installId),
  ]);
  return { status: "deleted" };
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const limit = Number(env.MAX_BODY_BYTES ?? 262144);
  if (url.pathname === "/v1/health" && request.method === "GET") {
    return reply(200, { status: "ok" });
  }
  if (request.method !== "POST" || !["/v1/batch", "/v1/delete"].includes(url.pathname)) {
    return reply(404, { error: "not found" });
  }
  const { value, error } = await readJson(request, limit);
  if (error) return error;
  if (url.pathname === "/v1/batch") {
    const found = problems(batchValidator, value);
    if (found) return reply(422, { error: "invalid batch", problems: found });
    return reply(200, await addBatch(env.DB, value));
  }
  const found = problems(deleteValidator, value);
  if (found) return reply(422, { error: "invalid request", problems: found });
  return reply(200, await deleteInstall(env.DB, value.install_id));
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch {
      return reply(500, { error: "server error" });
    }
  },
};
