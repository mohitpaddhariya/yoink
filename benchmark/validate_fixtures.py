"""Static fixture sanity-check — runs in milliseconds, before any money is spent building sessions.

Catches the structural mistakes that would silently break grading or session-building:
malformed JSON, non-user turns (build_session replays only user turns), unrecognized/empty
expectations, and the subtle one — a `conclusion_excludes` keyword that overlaps a
`conclusion_contains` keyword (which would make a correct answer un-gradeable).

    uv run python benchmark/validate_fixtures.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

from evalkit import _RECOGNIZED_EXPECT_KEYS, load_fixtures

CATEGORIES = {
    "conclusion_recall", "dead_end_suppression", "ruled_out_recall", "temporal_update",
    "abstention", "session_resolution", "long_transcript_stress",
}


def _issues(fx) -> list[str]:
    out = []
    if fx.category not in CATEGORIES:
        out.append(f"unknown category {fx.category!r}")
    if not fx.turns or any(role != "user" or not str(text).strip() for role, text in fx.turns):
        out.append("turns must be non-empty and all role 'user' (build replays user turns only)")
    expect = fx.expect or {}
    if not (_RECOGNIZED_EXPECT_KEYS & set(expect)):
        out.append("no recognized expect keys (grade would fail it)")
    contains = [k.lower() for k in expect.get("conclusion_contains", [])]
    excludes = [k.lower() for k in expect.get("conclusion_excludes", [])]
    for ex in excludes:
        for con in contains:
            if ex in con or con in ex:
                out.append(f"conclusion_excludes {ex!r} overlaps conclusion_contains {con!r}")
    if fx.category == "abstention":
        if not expect.get("no_conclusion"):
            out.append("abstention fixture must set no_conclusion=true")
        if contains:
            out.append("abstention fixture must NOT set conclusion_contains")
    if fx.category == "session_resolution" and not fx.session_hint:
        out.append("session_resolution fixture must set session_hint")
    return out


def main() -> int:
    fixtures = load_fixtures()
    by_cat = Counter(fx.category for fx in fixtures)
    problems = {fx.id: _issues(fx) for fx in fixtures}
    problems = {fid: iss for fid, iss in problems.items() if iss}

    print(f"loaded {len(fixtures)} fixtures")
    for cat in sorted(CATEGORIES):
        print(f"  {cat:<24} {by_cat.get(cat, 0)}")
    if by_cat.get(None):
        print(f"  {'(uncategorized)':<24} {by_cat[None]}")

    if problems:
        print(f"\n{len(problems)} fixture(s) with issues:")
        for fid, iss in sorted(problems.items()):
            for msg in iss:
                print(f"  FAIL {fid}: {msg}")
        return 1
    print("\nall fixtures structurally valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
