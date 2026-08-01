"""Enhanced-dashboard structure (2026-08-01): the conspicuous pieces must
exist in panel.html — a redesign that renders nothing is a text label."""
from pathlib import Path

PANEL = (Path(__file__).resolve().parents[1] / "ops" / "panel.html").read_text()


def test_edge_lab_identity():
    assert "EDGE LAB" in PANEL
    assert "new-badge" in PANEL
    assert "--edge1" in PANEL and "--edge2" in PANEL     # purple/cyan tokens


def test_edge_command_cockpit_on_live_page():
    live = PANEL.split('id="tab-live"', 1)[1].split('id="tab-pairs"', 1)[0] \
        if 'id="tab-pairs"' in PANEL else PANEL.split('id="tab-live"', 1)[1][:6000]
    assert "EDGE COMMAND" in live
    for el in ("ec-pipeline", "ec-admission", "ec-trusted", "ec-decay",
               "ec-floor", "ec-hotq"):
        assert f'id="{el}"' in PANEL, el


def test_pipeline_stages_present():
    for stage in ("stamped episodes", "replay-eligible", "probe seats",
                  "trusted", "decaying"):
        assert stage in PANEL, stage


def test_governance_cards_and_ledger():
    for el in ("gc-evidence", "gc-risk", "gc-autonomy", "gc-docket", "gc-ledger"):
        assert f'id="{el}"' in PANEL, el


def test_script_tags_balanced():
    assert PANEL.count("<script") == PANEL.count("</script>")
