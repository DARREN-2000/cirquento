"""Make the suite runnable with or without pytest installed.

The tests are written in pytest style because that is what a reviewer expects.
But CI must be able to prove the engine works on a bare interpreter, so when
pytest is absent this shim provides just enough of it (`@pytest.fixture`) for
`python tests/run_all.py` to execute the identical test bodies.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:  # pragma: no cover
    import pytest  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    shim = types.ModuleType("pytest")

    def fixture(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._is_fixture = True  # type: ignore[attr-defined]
        return fn

    class _Raises:
        def __init__(self, expected: type[BaseException]) -> None:
            self._expected = expected

        def __enter__(self) -> "_Raises":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc_type is None:
                raise AssertionError(f"Expected {self._expected.__name__} but nothing was raised")
            return issubclass(exc_type, self._expected)

    shim.fixture = fixture  # type: ignore[attr-defined]
    shim.raises = _Raises  # type: ignore[attr-defined]
    sys.modules["pytest"] = shim
