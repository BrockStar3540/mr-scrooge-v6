"""tests/conftest.py — put the repo root on sys.path so `modules.*`, `config.*`
and `core.*` import cleanly no matter where pytest is invoked from."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Review round 2: last-known-good isolation ────────────────────────────────
# Path-scoped LKG state must never leak between tests (reproduced: 4/5 random
# orderings failed before this fixture + PathLKG). Belt and suspenders: clear
# on entry AND exit of every test.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_config_lkg():
    import config.runtime as _rt
    import modules.management.party_package as _ppm
    _rt._runtime_lkg.forget()
    _ppm._pp_lkg.forget()
    yield
    _rt._runtime_lkg.forget()
    _ppm._pp_lkg.forget()
