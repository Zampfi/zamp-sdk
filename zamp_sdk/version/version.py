"""Runtime SDK version.

Single source of truth resolved from the installed package metadata so that
logs and callers report the same version ``pyproject.toml`` declares, with no
second hard-coded copy to drift out of sync.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("zamp-sdk")
except PackageNotFoundError:  # e.g. a source checkout with no install metadata
    __version__ = "0.0.0+local"
