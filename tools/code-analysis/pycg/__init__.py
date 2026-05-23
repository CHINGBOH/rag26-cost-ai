"""Compatibility shim for the PyCG package on case-sensitive filesystems.

PyPI installs the package as ``PyCG`` but its own entrypoint imports ``pycg``.
Putting this directory on PYTHONPATH lets ``python3 -m PyCG`` resolve those
internal lowercase imports without modifying site-packages.
"""

from __future__ import annotations

from PyCG import *  # noqa: F401,F403
import PyCG as _PyCG

__path__ = _PyCG.__path__
