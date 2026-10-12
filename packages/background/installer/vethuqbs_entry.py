"""The frozen `vethuqbs` program: the background service (the PyInstaller entry script)."""

import multiprocessing

from vethuq_background.host import main

if __name__ == "__main__":
    # Needed so a frozen build can start worker processes (OCR and indexing use them).
    multiprocessing.freeze_support()
    main()
