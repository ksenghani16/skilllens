"""Split the difference between two skill texts into numbered changes (c1, c2, ...).

This is what lets the Verifier run a *controlled* experiment: it can put back
exactly one change (or a few) and leave everything else as in the new version.
"""
from __future__ import annotations

import difflib
from typing import Iterator, Optional

from .models import Change


def _opcodes(old: list[str], new: list[str]) -> Iterator[tuple[str, int, int, int, int, Optional[str]]]:
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    n = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            yield tag, i1, i2, j1, j2, None
        else:
            n += 1
            yield tag, i1, i2, j1, j2, f"c{n}"


def compute_changes(old_text: str, new_text: str) -> list[Change]:
    old, new = old_text.splitlines(keepends=True), new_text.splitlines(keepends=True)
    out: list[Change] = []
    for _tag, i1, i2, j1, j2, cid in _opcodes(old, new):
        if cid:
            out.append(Change(
                id=cid,
                old_lines=[l.rstrip("\r\n") for l in old[i1:i2]],
                new_lines=[l.rstrip("\r\n") for l in new[j1:j2]],
                old_start=i1 + 1, new_start=j1 + 1,
            ))
    return out


def apply_with_reverts(old_text: str, new_text: str, revert_ids: set[str]) -> str:
    """Return the NEW skill, except the listed changes are put back to their OLD text."""
    old, new = old_text.splitlines(keepends=True), new_text.splitlines(keepends=True)
    parts: list[str] = []
    for _tag, i1, i2, j1, j2, cid in _opcodes(old, new):
        if cid is None:
            parts.extend(old[i1:i2])
        elif cid in revert_ids:
            parts.extend(old[i1:i2])
        else:
            parts.extend(new[j1:j2])
    return "".join(parts)


def render_changes(changes: list[Change]) -> str:
    """Compact text form shown to the Investigator."""
    lines = []
    for c in changes:
        lines.append(f"CHANGE {c.id}")
        lines.append(f"  removed: {' / '.join(c.old_lines) if c.old_lines else '(nothing)'}")
        lines.append(f"  added: {' / '.join(c.new_lines) if c.new_lines else '(nothing)'}")
    return "\n".join(lines)
