"""The frozen `vethuq` command (the PyInstaller entry script)."""

import multiprocessing

from vethuq_cli.main import Cli

if __name__ == "__main__":
    # Needed so a frozen build can start worker processes (OCR and indexing use them).
    multiprocessing.freeze_support()
    Cli.run()
