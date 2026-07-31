"""B-114: popper-vs-parent classification must survive the LIVE account's
clientExtensions mangling (tag -> "0", comment truncated ~32 chars) in BOTH
comment formats — the 6.11.1 reorder put anc/lvl/psu first, which pushed
sl/tr past the truncation and silently orphaned four live GBP trades on
2026-07-31 (misclassified as parents, swallowed by one-parent-per-pair)."""
from core.engine import _looks_like_popper


def T(comment, tag="0"):
    return {"tag": tag, "comment": comment}


def test_intact_tag_wins_regardless_of_comment():
    assert _looks_like_popper(T("garbage", tag="pp_v1"))


def test_new_format_truncated_live_copy_is_popper():
    # exactly what the live trades endpoint returned for trade 6565's siblings
    assert _looks_like_popper(T('{"anc":183.263,"lvl":15.0,"psu"'))
    assert _looks_like_popper(T('{"anc":1.34303,"lvl":30.0,"ps'))


def test_old_format_truncated_still_popper():
    assert _looks_like_popper(T('{"sl":60.0,"tr":8.5,"tp":2.5,"an'))


def test_parent_comments_never_match():
    assert not _looks_like_popper(T('{"su":"timing_lean_30_t20s","m":'))     # truncated parent
    assert not _looks_like_popper(T('{"m":"ratchet","sl":40.0,"tr":8.5'))    # legacy parent, sl/tr visible
    assert not _looks_like_popper(T(""))
    assert not _looks_like_popper(T("manual close"))


def test_untruncated_practice_copies_both_ways():
    assert _looks_like_popper(T('{"anc":183.263,"lvl":15.0,"psu":"timing_lean_30_t20s","sl":60.0,"tr":8.5,"tp":2.5,"su":"pp_v1"}'))
    assert not _looks_like_popper(T('{"su":"control_rvol_60_t20s","m":"ratchet","sl":60.0,"tr":20.0,"tp":2.5}'))
