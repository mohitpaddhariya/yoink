# Does yoink actually work — and is it cheaper?

Three questions, measured on **real Claude sessions** (built, resumed, and answered through the same
`claude -p --resume` path the product uses), not estimated:

1. **Does it recall the right answer?** → Track A
2. **Is it cheaper than the alternatives?** → Track B
3. **Does it hold up as sessions get big?** → Track C

Run it all: `uv run python benchmark/run.py` · watch progress from any terminal:
`uv run python benchmark/progress.py`.

> **These numbers survived three review passes.** A code review caught the first cut *flattering* yoink
> (a baseline wrote the answer into the session yoink then read; cross-method metrics were asymmetric).
> Two ML-review passes then caught grader false-negatives — an abstention over-claim, an over-easy
> stress test, and a blunt anti-leak check that failed correct answers for *naming* a ruled-out term.
> All fixed; a tried-then-reverted output-shortening that hurt recall is documented below too. Honest
> beats flattering.

## 1. Recall accuracy

100 fixtures across 7 task types. Each becomes a real session; yoink recalls it (Haiku) and a grader
(substring + synonym aliases + light normalization) checks the answer. **"dead-end leak" = a ruled-out
guess showing up in the conclusion.**

![accuracy](accuracy.png)

| Task type | What it tests | Accuracy | Dead-end leak |
|---|---|--:|--:|
| temporal_update | uses the latest decision, not the superseded one | **100%** | — |
| ruled_out_recall | lists what was abandoned | **100%** | — |
| dead_end_suppression | returns the ratified cause, not the dead ends | **94%** | **0%** |
| conclusion_recall | finds the final decision | **93%** | — |
| long_transcript_stress | conclusion buried in a long, noisy session | **86%** | **0%** |
| session_resolution | finds the right session from a fuzzy hint (among ~100) | 77% | — |
| abstention | true-abstain or flag a tentative hypothesis (not over-claim) | 71% | — |
| **Overall** | | **89%** | **0%** |

**What's strong — and it's the part that matters:**

- **0% dead-end leak.** Across every fixture with a ruled-out guess, yoink *never once* put the dead
  end in its conclusion (they go in a separate `ruled_out` field). That's the whole premise.
- **100% on recency and on listing what was ruled out; 93–94% on the core decision tasks.**
- **It never over-claims.** Abstention **precision 1.00** (recall 0.78, F1 0.88) — when yoink commits,
  the session had concluded. No-conclusion cases are split into *true-abstention* (must stay silent)
  and *tentative hypothesis* (may report a likely-but-unconfirmed cause **if** it flags it
  `hypothesis_only`); the recall variance is on whether it tags the tentative ones, never on inventing.

**Where it's weaker, plainly:** picking the right session from a fuzzy hint among ~100 (**77%**, up
from 54% → 69% → 77% across resolver rewrites) and the *tentative-hypothesis* half of abstention
(it abstains cleanly but doesn't always tag a hypothesis as tentative). These keep the overall at
**89%, just under the 90% target**. Real limitations, reported, not hidden.

## 2. Cost & latency vs the alternatives

The same question answered four ways over 6 real sessions (dead-end cases + 5K/25K/100K haystacks).
Baselines are tool-disabled like yoink, and the full-transcript baseline reads the **actual** session
transcript. **Live-context = tokens you end up carrying to get the answer.**

| Method | Answer accuracy ↑ | p50 latency ↓ | Cost/q ↓ | Live-context ↓ |
|---|--:|--:|--:|--:|
| grep | _evidence only*_ | **11 ms** | **$0.000** | 48,310 |
| read it yourself (Opus, full transcript) | 100% | 10.2 s | $0.443 | 22,254 |
| resume it yourself (Opus) | 100% | 9.3 s | $0.424 | 41,630 |
| **yoink (Haiku recall)** | 100% | 15.5 s | **$0.070** | **908** |

<sub>*grep doesn't answer — it returns matching lines. "Evidence only" = the gold keyword is
*somewhere* in the 48,310 tokens it dumps at you, which you still have to read. Not comparable to the
answer-accuracy of the other three.</sub>

**Everyone finds the answer on these clear cases — the difference is what it costs and what it leaves
in your lap.** yoink answers for **$0.070** (~6× cheaper than reading/resuming with Opus) and hands
back **~900 tokens** instead of leaving you on the 22K–48K-token transcript — **25–53× less to carry.**
(Latency is comparable — a touch slower here as the recall fork spins up; the win is cost and context.)

By session size the cost gap widens (measured `total_cost_usd`):

| Session | read it yourself | yoink | |
|---|--:|--:|--:|
| small (~5K) | $0.18 | **$0.04** | 5.0× |
| medium (~25K) | $0.49 | **$0.08** | 6.5× |
| big (~100K) | $1.70 | **$0.23** | **7.3×** |

![cost](cost.png)

## 3. Long-context stress — by size AND difficulty

A known conclusion buried in synthetic sessions from 5K–100K tokens, stated three ways: **easy**
(explicit `FINAL CONCLUSION:` marker), **medium** (natural prose, no marker), **hard** (implied across
turns with a correction off a dead end). Difficulty is the honest knob — a marker is far easier than an
implied conclusion.

![stress](stress.png)

- **Easy, medium, AND hard all held at 100% across sizes.** yoink pulled the conclusion at every size
  and every difficulty — even when the conclusion is only *implied*, after a correction off a dead end,
  with no marker. (An earlier run showed the 25K hard cell "failing"; that was a grader false-negative
  — the model answered correctly but *named* the dead end as ruled-out, which the blunt anti-leak check
  wrongly flagged. Context-aware grading fixed it; the difficulty levels are still real, the model just
  handles them.)
- **Cost scales gently:** **$0.026 → $0.053 → $0.158** for 5K → 25K → 100K.
- **Distractors don't fool it**, and it **picks the updated decision over the superseded one** at scale.
- **On the unanswerable cell it correctly abstains** (no_conclusion, confidence none) — and naming a
  ruled-out term while abstaining no longer counts as a leak (the false-negative the review caught).

## Did it hit the bar?

The targets from [`STRATEGY.md`](STRATEGY.md) §2, and where v1 landed:

| Target | Result |
|---|---|
| ≤5% dead-end error rate | ✅ **0%** |
| high abstention precision (never invent) | ✅ **1.00** (recall 0.78, F1 0.88) |
| ≥3× lower cost than full transcript (medium) | ✅ **6.5×** ($0.075 vs $0.490) |
| ≥10× lower live-context than full transcript | ✅ **25×** (908 vs 22,254 tokens) |
| ≥90% recall accuracy | ⚠️ **89%** overall — *so close* (100% ruled-out + temporal, 93–94% core decision; fuzzy resolution 77% + tentative-abstention tagging keep it just under) |

## How it's measured (honestly)

- **Real sessions, real path.** Each fixture's user turns are replayed through `claude -p` to build a
  genuine on-disk session; recall runs the production `run_answerer` (`--resume --fork-session
  --tools "" --permission-mode plan`, Haiku). Built sessions are cached (atomic write); failed calls
  are flagged and dropped, never logged as $0.
- **Fair baselines.** native-resume forks (never pollutes the session yoink reads) and is
  tool-disabled like yoink; the full-transcript baseline reads the *real* JSONL transcript; token
  counts include cache-resident transcript tokens; live-context reflects the whole transcript a resume
  leaves in your session. grep is reported as evidence-containment, not answer accuracy.
- **Grader validity.** Synonym alias-groups (`conclusion_contains_any`) and hyphen/punctuation
  normalization, so "clock skew" satisfies "clock drift" and "60-second" satisfies "60 seconds".
  Anti-leak is **context-aware**: naming a dead end in *ruled-out / superseded* language ("postgres was
  ruled out") is correct, not a leak — only presenting it *as the cause* fails. Every cost/stress row
  stores its raw + parsed answer and grade reasons for audit.
- **`decision_status`.** The recall schema distinguishes *settled* / *hypothesis_only* / *open*, so a
  likely-but-unconfirmed cause is reported and flagged rather than forced into a false binary.
- **Compactness vs recall, decided honestly.** A tried output-shortening (hard word/item caps) cut
  recall ~13 points by dropping ruled-out items and the exact cause terms the grader checks — so it
  was reverted. ~900 returned tokens is already 25× lighter than the alternatives; trimming further
  needs a smarter approach than a word budget.
- **Synthetic & seeded.** v1 is 100 hand-authored fixtures across the 7 STRATEGY categories — "real
  seeded sessions", not arbitrary real-world coverage. A corpus of real annotated sessions (STRATEGY
  v2) is the honest next step.

## Reproduce

```bash
uv run python benchmark/run.py                 # all three tracks + graphs, behind the live tracker
uv run python benchmark/recall.py              # Track A only
uv run python benchmark/costbench.py           # Track B only
uv run python benchmark/stress.py              # Track C only
uv run python benchmark/progress.py            # peek at progress from another terminal
```

Raw results land in `results/*.json`; graphs regenerate from them.

## What this is not

Not a coding-agent benchmark. yoink is a **read-only memory-recall layer** for Claude Code sessions —
measured on recall quality, cost, and context economy, not on writing patches.

## References

Benchmark design draws on: **LongMemEval** (long-term memory: extraction, temporal reasoning,
abstention), **LoCoMo** (conversational memory with evidence turns), **RULER** (long-context stress
beyond needle-in-haystack), **LOFT** (long-context vs retrieval, cost framing), **Mem0** (memory
benchmark on accuracy + tokens + p95 latency). Full rationale in [`STRATEGY.md`](STRATEGY.md).
