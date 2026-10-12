"""PyInstaller runtime hook: make the add-ons in `<install folder>/add-ons/` importable.

Each add-on sits in its own folder there (`add-ons/pdf/`), holding its package and its
`*.dist-info`. VethuQ finds add-ons through their entry points, and `importlib.metadata` reads
those from every folder on `sys.path`, so putting each add-on folder on the path is all it takes.
Dropping another add-on folder in later makes it available.
"""

import os
import sys

_root = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "add-ons")
if os.path.isdir(_root):
    for _name in sorted(os.listdir(_root)):
        _folder = os.path.join(_root, _name)
        if os.path.isdir(_folder) and _folder not in sys.path:
            sys.path.append(_folder)
