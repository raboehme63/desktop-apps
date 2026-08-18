"""Standard logging setup. GUI code may attach additional handlers."""

from __future__ import annotations

import logging
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(*, level: int = logging.INFO, log_file: Path | None = None) -> None:
    """Configure the root logger once for library and application use."""

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    logging.basicConfig(level=level, format=_FORMAT)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
