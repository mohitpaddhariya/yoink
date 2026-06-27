"""Build + cache the real resumable sessions the benchmark recalls against.

Recall is the product path, so the benchmark runs against REAL sessions, not inlined
transcripts. Each fixture's USER turns are replayed through ``claude -p --resume`` (the model
answers for real, briefly) so the on-disk transcript faithfully contains the dead-ends and the
ratified conclusion the fixture states. The fidelity rule (proven by tests/test_integration.py's
``_make_messy_session``): **the recall-relevant facts must live in user-authored turn text** —
the model only has to acknowledge them.

Isolation + cache: sessions are built from one dedicated cwd (``BENCH_CWD``) so they land in
their own project slug under ``CLAUDE_CONFIG_DIR``, never mixed into the user's real sessions,
and resume cleanly from that cwd. Building ~100 sessions costs real money, so refs are cached in
``results/sessions.json`` keyed by a hash of the fixture's turns and reused until the turns change.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import usage
from yoink import resolver

RESULTS_DIR = Path(__file__).parent / "results"
BENCH_CWD = RESULTS_DIR / "sessions_cwd"
CACHE_FILE = RESULTS_DIR / "sessions.json"
BUILD_MODEL = "claude-haiku-4-5"  # seeding is just transcript-writing; always the cheap model
TERSE = "\n\nReply in one short sentence; do not investigate."


def _turns_hash(turns) -> str:
    blob = json.dumps([list(t) for t in turns], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _user_turns(turns) -> list[str]:
    return [text for role, text in turns if role == "user"]


def _transcript_path(session_id: str) -> Path:
    return resolver.default_projects_root() / resolver.cwd_to_slug(str(BENCH_CWD)) / f"{session_id}.jsonl"


def _claude_turn(prompt: str, *, resume: str | None, model: str, timeout: float = 600) -> dict:
    cmd = ["claude", "-p"]
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--output-format", "json", "--tools", "", "--model", model]  # prompt via stdin
    run = usage.measure(cmd, input=prompt, cwd=str(BENCH_CWD), timeout=timeout)
    if run.returncode != 0:
        raise RuntimeError(f"claude exited {run.returncode}: {run.stderr.strip()[:300]}")
    m = usage.envelope_metrics(run.stdout)
    if not m or m["is_error"] or not m["session_id"]:
        raise RuntimeError(f"claude returned no usable session: {(run.stdout or '')[:300]}")
    return m


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


_cache_lock = threading.Lock()


def _is_cached(cache: dict, fixture) -> dict | None:
    c = cache.get(fixture.id)
    if c and c.get("hash") == _turns_hash(fixture.turns) and _transcript_path(c["session_id"]).exists():
        return c
    return None


def _build_one(fixture, model: str) -> dict:
    prompts = _user_turns(fixture.turns)
    if not prompts:
        raise ValueError(f"fixture {fixture.id!r} has no user turns to build a session from")
    sid: str | None = None
    cost, size = 0.0, 0
    for text in prompts:  # turns are a resume-chain → must run in order for THIS session
        m = _claude_turn(text + TERSE, resume=sid, model=model)
        sid = m["session_id"]
        cost += m["cost_usd"] or 0.0
        size += usage.count_tokens(text)
    return {"fixture_id": fixture.id, "session_id": sid, "cwd": str(BENCH_CWD),
            "size_tokens": size, "build_cost_usd": round(cost, 4), "hash": _turns_hash(fixture.turns)}


def build_session(fixture, *, model: str = BUILD_MODEL, force: bool = False) -> dict:
    """Build (or reuse from cache) a real resumable session for ``fixture``."""
    BENCH_CWD.mkdir(parents=True, exist_ok=True)
    cache = _load_cache()
    if not force and (hit := _is_cached(cache, fixture)):
        return hit
    ref = _build_one(fixture, model)
    with _cache_lock:
        cache = _load_cache()
        cache[fixture.id] = ref
        _save_cache(cache)
    return ref


def build_all(fixtures, *, tracker=None, model: str = BUILD_MODEL, max_workers: int = 8) -> dict:
    """Build/reuse every fixture's session in parallel (each session's own turns stay sequential).

    Returns {fixture_id: ref}. Cache is written after each build (under a lock) so a crash never
    wastes the sessions already paid for. Drives the tracker if given.
    """
    BENCH_CWD.mkdir(parents=True, exist_ok=True)
    cache = _load_cache()
    refs = {fx.id: hit for fx in fixtures if (hit := _is_cached(cache, fx))}
    to_build = [fx for fx in fixtures if fx.id not in refs]
    if tracker:
        tracker.phase("building sessions", len(fixtures))
        tracker.step("cached", n=len(refs))

    def work(fx):
        ref = _build_one(fx, model)
        with _cache_lock:
            cur = _load_cache()
            cur[fx.id] = ref
            _save_cache(cur)
        if tracker:
            tracker.step(fx.id)
        return fx.id, ref

    if to_build:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for fid, ref in pool.map(work, to_build):
                refs[fid] = ref
    if tracker:
        tracker.done_phase()
    return refs


# --- Track C: conclusion-in-haystack generator -------------------------------------------

def make_haystack(
    *, fixture_id: str, question: str, target_tokens: int, position: str = "end",
    distractors: int = 10, conclusion: str | None = None, deadend: str = "postgres",
    superseded: str | None = None, topic: str = "the intermittent post-deploy auth failures",
):
    """A fixture-like object whose ONE big user turn buries the evidence among ~``target_tokens``
    of distractor chatter. position ∈ {start,mid,end}. Variants:
      - normal: ``conclusion`` set → expect that, excluding ``deadend``.
      - update: ``superseded`` set → an early decision overwritten by ``conclusion`` (recency test).
      - unanswerable: ``conclusion=None`` → no decision; expect abstention, ``deadend`` floated only.
    """
    dead_lines = [f"Earlier I suspected {deadend} #{i}, but ruled it out after checking." for i in range(distractors)]
    # ponytail: ~4 chars/token; pad with varied log-ish lines until we reach target size.
    filler, n = [], 0
    target_chars = target_tokens * 4
    while sum(len(s) for s in filler) < target_chars:
        filler.append(f"[note {n}] reviewed logs/config for {topic}; nothing conclusive in this slice.")
        n += 1
    body = dead_lines + filler
    if superseded:
        body = [f"Early on I concluded the cause of {topic} was {superseded}."] + body
    cut = {"start": 0, "mid": len(body) // 2, "end": len(body)}.get(position, len(body))
    concl_lines = [f"FINAL CONCLUSION: the cause of {topic} is {conclusion}."] if conclusion else []
    lines = body[:cut] + concl_lines + body[cut:]
    big_turn = f"Here are my full working notes on {topic}. Read them as your own prior context:\n\n" + "\n".join(lines)

    if conclusion is None:
        big_turn += "\n\nI never reached a firm conclusion — this is still open."
        expect = {"no_conclusion": True, "conclusion_excludes": [deadend]}
    else:
        expect = {"conclusion_contains": [conclusion], "conclusion_excludes": [superseded or deadend], "no_conclusion": False}
    return SimpleNamespace(
        id=fixture_id, question=question, turns=[("user", big_turn)],
        category="long_transcript_stress", session_hint=topic, expect=expect,
    )


# --- selftest: the make-or-break smoke for A/C -------------------------------------------

def _selftest() -> int:
    from yoink.answerer import run_answerer
    from yoink.prompts import build_recall_prompt

    messy = SimpleNamespace(
        id="_selftest_messy",
        question="What did you conclude was causing the auth failures?",
        turns=[
            ("user", "We are debugging: auth requests fail intermittently about an hour after deploy. "
                     "My first hypothesis is the cache holding a stale entry."),
            ("user", "Update: ruled out the cache (TTL is 30s, far under an hour). The real cause is the "
                     "token refresh path reusing an access token already expired at the 1h mark."),
        ],
        expect={},
    )
    ref = build_session(messy, force=True)
    print(f"built {ref['session_id']} (cwd={ref['cwd']}, ~{ref['size_tokens']} tok, ${ref['build_cost_usd']})")

    res = run_answerer(ref["session_id"], ref["cwd"], build_recall_prompt(messy.question), model=BUILD_MODEL)
    assert res.ok, res.error
    answer = res.answer.answer.lower()
    ruled = " ".join(res.answer.ruled_out).lower()
    print(f"recall: {res.answer.answer!r} | ruled_out={res.answer.ruled_out}")
    assert "token refresh" in answer, f"ratified conclusion missing: {answer!r}"
    assert "cache" in ruled or "cache" in answer, f"dead end not recorded: {ruled!r}"
    print("sessions.py selftest ok")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(f"sessions cache: {CACHE_FILE} ({len(_load_cache())} entries); build cwd: {BENCH_CWD}")
