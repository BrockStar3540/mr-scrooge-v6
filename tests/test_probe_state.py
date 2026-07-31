"""PROBE seat (charter, 2026-07-31): a reduced-size audition between SHADOW
and ACTIVE — fires like ACTIVE, sized at pm_probe_mult, generates real broker
cycles cheaply. DISABLED remains sacred."""
from modules.cells.cell import CellIntent
from modules.playmaker.playmaker import pm_probe_mult


def test_probe_default_flag_false():
    import dataclasses
    f = {x.name: x for x in dataclasses.fields(CellIntent)}
    assert f["probe"].default is False


def test_probe_mult_sane():
    m = pm_probe_mult()
    assert 0.0 < m <= 1.0


def test_probe_status_is_legal_on_server():
    from ops.server import _CELL_STATUSES
    assert "PROBE" in _CELL_STATUSES and "DISABLED" in _CELL_STATUSES
