-- Counted events (a run that ran out of credits, a search), in buckets only: see "events" in
-- ../../schema/v1/batch.schema.json.
CREATE TABLE events (
  install_id TEXT NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL,
  engine TEXT NOT NULL,
  query_len TEXT NOT NULL,
  script TEXT NOT NULL,
  results TEXT NOT NULL,
  latency TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (install_id, day, kind, engine, query_len, script, results, latency)
);
CREATE INDEX events_day ON events (day);
