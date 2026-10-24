"""Make the repository root importable so `from tests.fakes import ...` works.

``python -m pytest`` happens to put the working directory on ``sys.path``;
the bare ``pytest`` entry point does not, and CI uses the latter. Without this
the shared test doubles fail to import and the whole suite errors during
collection — which is exactly how it behaved the first time the suite was
wired into CI.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
