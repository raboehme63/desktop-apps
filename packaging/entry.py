"""Frozen Windows entry point. Application packages are not modified.

``multiprocessing.freeze_support`` must run in the frozen main module so that
ProcessPool workers (import hashing, thumbnails) do not open extra GUI windows.
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from traveljournal.main import main

    raise SystemExit(main())
