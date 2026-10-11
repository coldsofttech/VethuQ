# Job protocol v1

Planned: the encrypted manifest and result formats shared by the client and the worker.

- `manifest.schema.json`: protocol version, job id, user settings, page list, licence token(s) and
  add-on entitlements, per-job caps, batching info.
- `result.schema.json`: per-page text, lines, confidence, phase, language, timings and billable
  duration, partial-result marker, metrics.
- `examples/` and `fixtures/`: synthetic data used by both sides' tests.

Changes within v1 are additive; unknown major versions are refused by client and worker.
