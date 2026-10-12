"""`vethuq-worker run --job-id ID --payload DIR --out DIR` (key in `VETHUQ_MASTER_KEY`)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from importlib.metadata import version
from pathlib import Path

from vethuq_worker.errors import JobError
from vethuq_worker.worker import Worker


class WorkerCli:
    """The `vethuq-worker` command."""

    KEY_VARIABLE = "VETHUQ_MASTER_KEY"
    EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

    @classmethod
    def main(cls, argv: list[str] | None = None, worker: Worker | None = None) -> int:
        """Run the command. `worker` is for tests and other hosts; the default reads with VethuQ."""
        args = cls._parser().parse_args(argv)
        if args.command == "bake-models":
            return cls._bake(args.models)

        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
        key = os.environ.get(cls.KEY_VARIABLE, "")
        if not key:
            print(f"{cls.KEY_VARIABLE} is not set.", file=sys.stderr)
            return cls.EXIT_USAGE
        try:
            result = (worker or Worker()).run(args.job_id, args.payload, args.out, key)
        except JobError as error:
            print(f"{error.code}: {error.message}", file=sys.stderr)
            return cls.EXIT_USAGE
        ok = sum(1 for page in result.pages if page.ok)
        print(f"job {args.job_id}: {result.status}, {ok}/{len(result.pages)} pages read")
        return cls.EXIT_FAILED if result.status == "failed" else cls.EXIT_OK

    @staticmethod
    def _parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="vethuq-worker")
        parser.add_argument(
            "--version", action="version", version=f"vethuq-worker {version('vethuq-worker')}"
        )
        commands = parser.add_subparsers(dest="command", required=True)
        run = commands.add_parser("run", help="read a job's pages")
        run.add_argument("--job-id", required=True)
        run.add_argument("--payload", required=True, type=Path, help="folder holding payload.bin")
        run.add_argument("--out", required=True, type=Path, help="folder to write result.bin to")
        bake = commands.add_parser("bake-models", help="download the OCR models (image build)")
        bake.add_argument("--models", required=True, type=Path)
        return parser

    @classmethod
    def _bake(cls, models: Path) -> int:
        from vethuq_worker.bake import BakeError, Baker

        try:
            count = Baker(models).run()
        except BakeError as error:
            print(str(error), file=sys.stderr)
            return cls.EXIT_FAILED
        print(f"{count} engine(s) ready in {models}")
        return cls.EXIT_OK
