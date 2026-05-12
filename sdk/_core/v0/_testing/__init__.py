from __future__ import annotations

from .common import AllowedOverlap, TestFailure, TestReport
from .context import TestContext

__all__ = [
    "AllowedOverlap",
    "TestContext",
    "TestFailure",
    "TestReport",
]

_COMPAT_MODULE = "sdk._core.v0.testing"
for _name in __all__:
    _obj = globals().get(_name)
    if getattr(_obj, "__module__", "").startswith("sdk._core.v0._testing"):
        try:
            _obj.__module__ = _COMPAT_MODULE
        except Exception:
            pass

del _COMPAT_MODULE, _name, _obj
