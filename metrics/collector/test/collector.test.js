import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { addBatch, handle, prune, LIMITS } from "../src/index.js";

const examples = new URL("../../schema/v1/examples/", import.meta.url);
const example = (name) => JSON.parse(readFileSync(new URL(name, examples), "utf8"));

// A D1 look-alike over node:sqlite, so the real SQL and migration run in the tests.
function d1() {
  const sqlite = new DatabaseSync(":memory:");
  for (const file of ["0001_init.sql", "0002_events.sql"]) {
    sqlite.exec(readFileSync(new URL(`../migrations/${file}`, import.meta.url), "utf8"));
  }
  const statement = (sql, args = []) => ({
    bind: (...values) => statement(sql, values),
    run: async () => ({ meta: { changes: Number(sqlite.prepare(sql).run(...args).changes) } }),
    all: async () => ({ results: sqlite.prepare(sql).all(...args) }),
    first: async () => sqlite.prepare(sql).get(...args) ?? null,
  });
  return {
    sqlite,
    prepare: (sql) => statement(sql),
    batch: async (statements) => {
      sqlite.exec("BEGIN");
      try {
        for (const s of statements) await s.run();
        sqlite.exec("COMMIT");
      } catch (e) {
        sqlite.exec("ROLLBACK");
        throw e;
      }
    },
  };
}

const post = (path, body, env) =>
  handle(
    new Request(`https://x.test${path}`, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) }),
    env,
  );
const count = (db, table) => db.sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;

let env;
beforeEach(() => {
  env = { DB: d1(), MAX_BODY_BYTES: "20000" };
});

describe("the schema examples", () => {
  for (const name of readdirSync(examples)) {
    it(`${name} is ${name.startsWith("valid") ? "accepted" : "refused"}`, async () => {
      const response = await post("/v1/batch", example(name), env);
      expect(response.status).toBe(name.startsWith("valid") ? 200 : 422);
    });
  }
});

describe("POST /v1/batch", () => {
  it("adds the day's totals", async () => {
    const response = await post("/v1/batch", example("valid-full.json"), env);
    expect(await response.json()).toEqual({ status: "ok", days: 1 });
    expect(count(env.DB, "usage")).toBe(2);
    expect(count(env.DB, "failures")).toBe(1);
    expect(count(env.DB, "installs")).toBe(1);
  });

  it("counts a batch that is sent twice once", async () => {
    await post("/v1/batch", example("valid-full.json"), env);
    const again = await post("/v1/batch", example("valid-full.json"), env);
    expect(await again.json()).toEqual({ status: "duplicate" });
    const pages = env.DB.sqlite.prepare("SELECT SUM(pages) AS n FROM usage").get().n;
    expect(pages).toBe(50);
  });

  it("adds up different batches for the same day", async () => {
    const first = example("valid-full.json");
    const second = { ...example("valid-full.json"), batch_id: "c".repeat(32) };
    await post("/v1/batch", first, env);
    await post("/v1/batch", second, env);
    expect(env.DB.sqlite.prepare("SELECT SUM(pages) AS n FROM usage").get().n).toBe(100);
    expect(count(env.DB, "usage")).toBe(2);
  });

  it("takes a heartbeat with no days", async () => {
    const response = await post("/v1/batch", example("valid-heartbeat.json"), env);
    expect(response.status).toBe(200);
    expect(count(env.DB, "usage")).toBe(0);
    expect(count(env.DB, "installs")).toBe(1);
  });

  it("refuses what is not json, and what is too large", async () => {
    expect((await post("/v1/batch", "not json", env)).status).toBe(400);
    expect((await post("/v1/batch", "x".repeat(30000), env)).status).toBe(413);
  });

  it("stores nothing from a refused batch", async () => {
    await post("/v1/batch", example("invalid-extra-field.json"), env);
    expect(count(env.DB, "batches")).toBe(0);
  });
});

describe("POST /v1/delete", () => {
  it("deletes everything held for an install, and only that", async () => {
    await post("/v1/batch", example("valid-full.json"), env);
    const other = { ...example("valid-full.json"), batch_id: "d".repeat(32), install_id: "e".repeat(32) };
    await post("/v1/batch", other, env);
    const response = await post("/v1/delete", { install_id: "b".repeat(32) }, env);
    expect(await response.json()).toEqual({ status: "deleted" });
    for (const table of ["usage", "failures", "batches", "installs"]) {
      expect(env.DB.sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE install_id = ?`).get("b".repeat(32)).n).toBe(0);
    }
    expect(count(env.DB, "installs")).toBe(1);
  });

  it("refuses a request that is not exactly an install id", async () => {
    expect((await post("/v1/delete", { install_id: "nope" }, env)).status).toBe(422);
    expect((await post("/v1/delete", { install_id: "b".repeat(32), extra: 1 }, env)).status).toBe(422);
  });
});

describe("routes", () => {
  it("answers health, and 404s the rest", async () => {
    expect((await handle(new Request("https://x.test/v1/health"), env)).status).toBe(200);
    expect((await handle(new Request("https://x.test/v1/batch"), env)).status).toBe(404);
    expect((await post("/elsewhere", {}, env)).status).toBe(404);
  });
});

describe("events, plausibility, limits and retention", () => {
  const full = () => example("valid-full.json");

  it("stores the counted events and deletes them with the install", async () => {
    await post("/v1/batch", full(), env);
    expect(count(env.DB, "events")).toBe(3);
    await post("/v1/delete", { install_id: full().install_id }, env);
    expect(count(env.DB, "events")).toBe(0);
  });

  it("refuses a batch no computer could make", async () => {
    const batch = full();
    batch.days[0].pages[0].pages = LIMITS.pagesPerRow + 1;
    const response = await post("/v1/batch", batch, env);
    expect(response.status).toBe(422);
    expect((await response.json()).reason).toBe("too many pages");
    expect(count(env.DB, "usage")).toBe(0);
  });

  it("refuses confidence above one hundred percent", async () => {
    const batch = full();
    batch.days[0].pages[0].confidence_sum = batch.days[0].pages[0].pages + 5;
    expect((await post("/v1/batch", batch, env)).status).toBe(422);
  });

  it("allows a few batches an install a day, then asks it to wait", async () => {
    const results = [];
    for (let i = 0; i < LIMITS.batchesPerInstallPerDay + 1; i++) {
      const batch = full();
      batch.batch_id = String(i).padStart(32, "0");
      results.push((await post("/v1/batch", batch, env)).status);
    }
    expect(results).toEqual([200, 200, 200, 429]);
  });

  it("limits by address when a limiter is bound", async () => {
    const limited = { ...env, IP_LIMITER: { limit: async () => ({ success: false }) } };
    expect((await post("/v1/batch", full(), limited)).status).toBe(429);
  });

  it("drops raw batch records after the retention, and keeps the totals", async () => {
    await post("/v1/batch", full(), env);
    const later = new Date(Date.now() + (LIMITS.retentionDays + 1) * 86_400_000);
    expect((await prune(env.DB, later)).removed).toBe(1);
    expect(count(env.DB, "batches")).toBe(0);
    expect(count(env.DB, "usage")).toBeGreaterThan(0);
  });
});
