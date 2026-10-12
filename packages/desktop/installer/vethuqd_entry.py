"""The frozen `vethuqd` program: the VethuQ desktop application (the PyInstaller entry script)."""

import multiprocessing

from vethuq_desktop.launcher import main

if __name__ == "__main__":
    # Needed so a frozen build can start worker processes (OCR and indexing use them).
    multiprocessing.freeze_support()
    raise SystemExit(main())
