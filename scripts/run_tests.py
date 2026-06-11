#!/usr/bin/env python3
"""Dependency-free test runner.

Uses real pytest when installed; otherwise falls back to a minimal
compatible shim supporting `pytest.raises`, `pytest.mark.parametrize`,
and the `tmp_path` fixture, which is all this suite needs.
"""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import itertools
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _build_shim() -> types.ModuleType:
    shim = types.ModuleType("pytest")

    @contextlib.contextmanager
    def raises(exc_type, match=None):
        import re as _re

        class Info:
            value = None
        info = Info()
        try:
            yield info
        except exc_type as exc:
            info.value = exc
            if match is not None and not _re.search(match, str(exc)):
                raise AssertionError(
                    f"{exc_type.__name__} message {str(exc)!r} "
                    f"does not match {match!r}")
        else:
            raise AssertionError(f"expected {exc_type.__name__} to be raised")

    class _Mark:
        def parametrize(self, argnames, argvalues):
            def deco(fn):
                params = getattr(fn, "_params", [])
                names = [n.strip() for n in argnames.split(",")]
                for vals in argvalues:
                    if len(names) == 1:
                        vals = (vals,)
                    params.append(dict(zip(names, vals)))
                fn._params = params
                return fn
            return deco

        def __getattr__(self, name):
            return lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))

    shim.raises = raises
    shim.mark = _Mark()
    return shim


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_one(fn, params: dict | None) -> tuple[bool, str]:
    kwargs = dict(params or {})
    sig = inspect.signature(fn)
    if "tmp_path" in sig.parameters:
        kwargs["tmp_path"] = Path(tempfile.mkdtemp())
    try:
        fn(**kwargs)
        return True, ""
    except Exception:
        return False, traceback.format_exc(limit=5)


def main() -> int:
    try:
        import pytest  # noqa: F401
        import subprocess
        return subprocess.call(
            [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"])
    except ImportError:
        pass

    sys.modules["pytest"] = _build_shim()
    sys.path.insert(0, str(ROOT))

    passed = failed = 0
    failures: list[tuple[str, str]] = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        mod = _load_module(path)
        for name, fn in sorted(vars(mod).items()):
            if not (name.startswith("test_") and callable(fn)):
                continue
            param_sets = getattr(fn, "_params", [None])
            for i, params in enumerate(param_sets):
                label = f"{path.name}::{name}" + (f"[{i}]" if params else "")
                ok, err = _run_one(fn, params)
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failures.append((label, err))

    for label, err in failures:
        print(f"FAILED {label}\n{err}")
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
