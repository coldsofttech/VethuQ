"""The frozen `vethuqw` program: the worker (the PyInstaller entry script)."""

import multiprocessing
import sys

from vethuq_worker.cli import WorkerCli

if __name__ == "__main__":
    # Needed so a frozen build can start worker processes (OCR uses them).
    multiprocessing.freeze_support()
    raise SystemExit(WorkerCli.main(sys.argv[1:]))
