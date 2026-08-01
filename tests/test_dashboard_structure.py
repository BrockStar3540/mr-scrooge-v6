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


def test_every_pane_div_balanced():
    """The bug Brock caught by eye (2026-08-01): one stray </div> in a pane
    breaks tab switching for every pane after it. Structural invariant now."""
    import re
    panes = [(m.start(), m.group(1))
             for m in re.finditer(r'<div id="(tab-\w+)" class="pane', PANEL)]
    assert len(panes) >= 8
    for i, (pos, name) in enumerate(panes):
        end = panes[i + 1][0] if i + 1 < len(panes) else PANEL.find("<script")
        seg = PANEL[pos:end]
        opens = len(re.findall(r"<div\b", seg))
        closes = seg.count("</div>")
        assert opens == closes, f"{name}: {opens} opens vs {closes} closes"
