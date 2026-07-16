"""tests/conftest.py — put the repo root on sys.path so `modules.*`, `config.*`
and `core.*` import cleanly no matter where pytest is invoked from."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
