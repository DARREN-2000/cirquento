"""Zero-dependency test runner.

pytest is the normal path (`make test`), but the demo, the container and this
runner must work on a bare Python with nothing installed — otherwise "does it
actually run?" depends on a successful pip install, which is exactly the
question nobody can answer offline.

Supports the small pytest subset the suite uses: module-level `test_*`
functions and simple no-argument fixtures resolved by parameter name.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

TESTS_DIR = Path(__file__).parent


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _fixtures(module: Any) -> dict[str, Callable[[], Any]]:
    found: dict[str, Callable[[], Any]] = {}
    for name, obj in vars(module).items():
        if callable(obj) and getattr(obj, "_is_fixture", False):
            found[name] = obj
    return found


def main() -> int:
    # conftest installs the pytest shim and the src/ path; it must load first.
    conftest = TESTS_DIR / "conftest.py"
    if conftest.exists():
        _load(conftest)

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    for path in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            module = _load(path)
        except ModuleNotFoundError as e:
            print(f"  ? Skipped {path.stem} (missing dependency: {e})")
            continue
            
        fixtures = _fixtures(module)
        for name, fn in sorted(vars(module).items()):
            if not (name.startswith("test_") and callable(fn)):
                continue
            label = f"{path.stem}::{name}"
            try:
                kwargs = {
                    p: fixtures[p]()
                    for p in inspect.signature(fn).parameters
                    if p in fixtures
                }
                fn(**kwargs)
                passed.append(label)
                print(f"  ✓ {label}")
            except Exception:  # noqa: BLE001 - a runner reports, it does not judge
                failed.append((label, traceback.format_exc()))
                print(f"  × {label}")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    for label, tb in failed:
        print(f"\n--- {label} ---\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
