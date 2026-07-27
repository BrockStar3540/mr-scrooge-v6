"""tests/test_cell_config_schema.py — the canonical validator is ENFORCED.

External-review finding (2026-07-27): the schema validator had drifted to the
July-04 era and rejected all 18 live cell files, while the live hot-loader
enforced nothing and the test suite passed around it — exactly how a typo or
stale field reaches a trading process. From now on: every cell config must
pass the canonical validator, and the validator must actually catch garbage.
Schema evolution is fine — but it happens in the validator and the configs in
the SAME commit, or this test fails.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CELLS = REPO / "config" / "cells"

_spec = importlib.util.spec_from_file_location(
    "cell_config_validator", REPO / "research" / "tools" / "cell_config_validator.py")
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def _validate(path_or_dict, tmp_path=None, name="inline"):
    """Run the canonical validator (validate_file); returns error strings."""
    if isinstance(path_or_dict, dict):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(path_or_dict))
        return validator.validate_file(p).errors
    return validator.validate_file(Path(path_or_dict)).errors


ALL_FILES = sorted(CELLS.glob("*.json"))


def test_cell_config_files_exist():
    assert len(ALL_FILES) >= 8, "cell config directory looks empty — wrong repo root?"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.stem)
def test_every_live_cell_config_passes_canonical_validator(path):
    errors = _validate(path)
    assert not errors, f"{path.name} fails the canonical schema:\n  " + "\n  ".join(errors)


def test_validator_is_not_vacuous(tmp_path):
    """Prove the validator still bites: corrupt a real config and it must fail."""
    base = json.loads(ALL_FILES[0].read_text())
    name = base.get("pair", ALL_FILES[0].stem)
    sess = next(s for s, b in base["sessions"].items() if b.get("setups"))
    assert not _validate(copy.deepcopy(base), tmp_path, name), \
        "sanity: the uncorrupted config must pass from a tmp file too"

    bad_status = copy.deepcopy(base)
    bad_status["sessions"][sess]["setups"][0]["status"] = "YOLO"
    assert _validate(bad_status, tmp_path, name), "validator accepted an invalid status"

    bad_field = copy.deepcopy(base)
    bad_field["sessions"][sess]["setups"][0]["sl_pisp_typo"] = 12
    assert _validate(bad_field, tmp_path, name), "validator accepted an unknown setup field"

    bad_exit = copy.deepcopy(base)
    bad_exit["sessions"][sess]["setups"][0]["exit"]["mode"] = "martingale"
    assert _validate(bad_exit, tmp_path, name), "validator accepted an unknown exit mode"
