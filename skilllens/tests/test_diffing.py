from skilllens.diffing import apply_with_reverts, compute_changes

OLD = "a\nb\nc\nd\ne\n"
NEW = "a\nB\nc\nd\nE\nf\n"


def test_changes_are_numbered_and_located():
    changes = compute_changes(OLD, NEW)
    assert [c.id for c in changes] == ["c1", "c2"]
    assert changes[0].old_lines == ["b"] and changes[0].new_lines == ["B"]


def test_revert_roundtrip():
    changes = compute_changes(OLD, NEW)
    all_ids = {c.id for c in changes}
    assert apply_with_reverts(OLD, NEW, all_ids) == OLD     # revert everything -> old text
    assert apply_with_reverts(OLD, NEW, set()) == NEW       # revert nothing -> new text
    only_first = apply_with_reverts(OLD, NEW, {"c1"})
    assert "b" in only_first and "E" in only_first          # c1 reverted, c2 kept
