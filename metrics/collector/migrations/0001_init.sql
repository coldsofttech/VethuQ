-- Anonymous, aggregated usage metrics. No names, paths or text are ever stored: the schema in
-- ../../schema/v1/batch.schema.json rejects anything else before it gets here.

CREATE TABLE installs (
  install_id TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  vethuq TEXT NOT NULL,
  python TEXT NOT NULL,
  os TEXT NOT NULL,
  arch TEXT NOT NULL,
  cpu_bucket TEXT NOT NULL,
  ram_bucket TEXT NOT NULL,
  workers TEXT NOT NULL,
  retry_attempts INTEGER NOT NULL,
  languages TEXT NOT NULL,
  confidence_bands TEXT NOT NULL
);

-- Batches seen, so one that is sent twice is counted once.
CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY,
  install_id TEXT NOT NULL,
  received_at TEXT NOT NULL
);
CREATE INDEX batches_install ON batches (install_id);

CREATE TABLE usage (
  install_id TEXT NOT NULL,
  day TEXT NOT NULL,
  file_type TEXT NOT NULL,
  phase TEXT NOT NULL,
  language TEXT NOT NULL,
  engine TEXT NOT NULL,
  page_source TEXT NOT NULL,
  size_bucket TEXT NOT NULL,
  band TEXT NOT NULL,
  pages INTEGER NOT NULL,
  passes INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  confidence_sum REAL NOT NULL,
  credits_milli INTEGER NOT NULL,
  PRIMARY KEY (install_id, day, file_type, phase, language, engine, page_source, size_bucket, band)
);
CREATE INDEX usage_day ON usage (day);

CREATE TABLE failures (
  install_id TEXT NOT NULL,
  day TEXT NOT NULL,
  file_type TEXT NOT NULL,
  code TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (install_id, day, file_type, code)
);
CREATE INDEX failures_day ON failures (day);
