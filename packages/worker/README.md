# vethuq-worker

The job protocol (v1) and the worker that reads a job's pages on a GitHub runner.

- `vethuq_worker.JobBuilder` packs the pages to read into one encrypted payload; `ResultReader` reads
  the encrypted answer (`JobResult.to_ocr_results()` gives the pages). `Worker` reads a job:
  `Worker().run(job_id, payload_dir, out_dir, key)`, or `Worker.with_engine(engine)` to read with
  a given engine. The pieces are classes (`JobCrypto`, `Container`, `Images`, `Protocol`). Both sides use the same 256-bit master key.
- `vethuq-worker run --job-id ID --payload DIR --out DIR` is what the runner image executes. The key
  comes from the `VETHUQ_MASTER_KEY` environment variable; nothing is ever read from the network.

See `github/protocol/v1/README.md` in the VethuQ repository for the format.
