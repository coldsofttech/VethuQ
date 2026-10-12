"""The frozen `vethuqic` command: the interactive shell (the PyInstaller entry script)."""

import multiprocessing

from vethuq_interactive_cli.main import main

if __name__ == "__main__":
    # Needed so a frozen build can start worker processes (OCR and indexing use them).
    multiprocessing.freeze_support()
    main()
