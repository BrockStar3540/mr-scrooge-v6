"""config/safe_config.py — path-scoped last-known-good configuration state.

External review round 2 (2026-07-28): module-global LKG dicts leaked state
across config paths — test A monkeypatches a tmp path, caches a value, the
patch is restored, and test B inherits state that belongs to a file it never
read (reproduced: 4/5 random test orderings failed). The same design would
also haunt any future multi-instance or alternate-config-path deployment.

A PathLKG remembers values PER RESOLVED PATH, deep-copied both ways so cached
state can never be mutated in place. `forget()` exists for test isolation
(see the autouse fixture in tests/conftest.py).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class PathLKG(Generic[T]):
    def __init__(self) -> None:
        self._values: dict[str, T] = {}
        self._lock = RLock()

    @staticmethod
    def key(path: Path) -> str:
        return str(Path(path).expanduser().resolve(strict=False))

    def remember(self, path: Path, value: T) -> T:
        with self._lock:
            self._values[self.key(path)] = deepcopy(value)
            return deepcopy(value)

    def get(self, path: Path) -> Optional[T]:
        with self._lock:
            value = self._values.get(self.key(path))
            return deepcopy(value) if value is not None else None

    def forget(self, path: Optional[Path] = None) -> None:
        with self._lock:
            if path is None:
                self._values.clear()
            else:
                self._values.pop(self.key(path), None)
