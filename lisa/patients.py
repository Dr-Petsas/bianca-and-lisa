"""Umzug nach kern/ am 27.08.2026 - Re-Export, damit bestehende Importe halten."""

import sys as _sys

from kern import patients as _mod

_sys.modules[__name__] = _mod
