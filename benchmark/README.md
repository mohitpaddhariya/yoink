# Does yoink actually work — and is it cheaper?

Three questions, measured on **real Claude sessions** (built, resumed, and answered through the same
`claude -p --resume` path the product uses), not estimated:

1. **Does it recall the right answer?** → Track A
2. **Is it cheaper than the alternatives?** → Track B
3. **Does it hold up as sessions get big?** → Track C

Run it all: `uv run python benchmark/run.py` · watch progress from any terminal:
`uv run python benchmark/progress.py`.

> **These numbers survived two review passes.** A code review caught the first cut *flattering* yoink
> (a baseline wrote the answer into the session yoink then read; cross-method metrics were
> asymmetric). An ML-review pass then caught grader false-negatives, an abstention over-claim, and an
> over-easy stress test. All fixed; everything below is the corrected re-run. Honest beats flattering.

## 1. Recall accuracy

100 fixtures across 7 task types. Each becomes a real session; yoink recalls it (Haiku) and a grader
(substring + synonym aliases + light normalization) checks the answer. **"dead-end leak" = a ruled-out
guess showing up in the conclusion.**

![accuracy](accuracy.png)

| Task type | What it tests | Accuracy | Dead-end leak |
|---|---|--:|--:|
| temporal_update | uses the latest decision, not the superseded one | **100%** | — |
| dead_end_suppression | returns the ratified cause, not the dead ends | **94%** | **0%** |
| conclusion_recall | finds the final decision | **93%** | — |
| abstention | true-abstain or flag a tentative hypothesis (not over-claim) | 86% | — |
| ruled_out_recall | lists what was abandoned | 86% | — |
| session_resolution | finds the right session from a fuzzy hint (among ~100) | 69% | — |
| long_transcript_stress | conclusion buried in a long, noisy session | 64% | **0%** |
| **Overall** | | **85%** | **0%** |

**What's strong — and it's the part that matters:**

- **0% dead-end leak.** Across every fixture with a ruled-out guess, yoink *never once* put the dead
  end in its conclusion (they go in a separate `ruled_out` field). That's the whole premise.
- **It knows settled from tentative.** Abstention **F1 0.94** (precision **1.00**, recall **0.89**) —
  after splitting no-conclusion cases into *true-abstention* (must stay silent) and *tentative
  hypothesis* (may report a likely-but-unconfirmed cause **if** it flags it `hypothesis_only`). On the
  9 true cases it abstains; on the 5 tentative ones it flags the hypothesis instead of over-claiming.
  (The earlier 0.36 conflated the two — it demanded silence where a *flagged* hypothesis is correct.)
- **100% on recency, 93–94% on the core decision tasks.**

**Where it's weaker, plainly:** picking the right session from a fuzzy hint among ~100 (**69%**, up
from 54% after the resolver-v2 rewrite) and digging a conclusion out of a long noisy transcript
(**64%**). These pull the overall to 85%. Real limitations, reported, not hidden.

## 2. Cost & latency vs the alternatives

The same question answered four ways over 6 real sessions (dead-end cases + 5K/25K/100K haystacks).
Baselines are tool-disabled like yoink, and the full-transcript baseline reads the **actual** session
transcript. **Live-context = tokens you end up carrying to get the answer.**

| Method | Answer accuracy ↑ | p50 latency ↓ | Cost/q ↓ | Live-context ↓ |
|---|--:|--:|--:|--:|
| grep | _evidence only*_ | **11 ms** | **$0.000** | 48,310 |
| read it yourself (Opus, full transcript) | 100% | 9.3 s | $0.444 | 22,254 |
| resume it yourself (Opus) | 100% | 10.7 s | $0.427 | 41,880 |
| **yoink (Haiku recall)** | 100% | 11.1 s | **$0.070** | **890** |

<sub>*grep doesn't answer — it returns matching lines. "Evidence only" = the gold keyword is
*somewhere* in the 48,310 tokens it dumps at you, which you still have to read. Not comparable to the
answer-accuracy of the other three.</sub>

**Everyone finds the answer on these clear cases — the difference is what it costs and what it leaves
in your lap.** yoink answers for **$0.070** (~6× cheaper than reading/resuming with Opus) and hands
back **890 tokens** instead of leaving you on the 22K–48K-token transcript — **25–54× less to carry.**

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

- **Easy and medium held at 100% across all sizes; the *hard* variant is genuinely harder.** With an
  explicit marker (easy) or natural prose (medium), yoink pulled the conclusion at every size. The hard
  variant — conclusion only *implied*, after a correction off a dead end, no marker — passed **8 of 9**
  answerable cells (it missed the 25K cell this run). With one sample per cell it's noisy run-to-run,
  but the difficulty knob is real, not decorative — it no longer guarantees a pass the way the marker did.
- **Cost scales gently:** **$0.026 → $0.053 → $0.158** for 5K → 25K → 100K.
- **Distractors don't fool it**, and it **picks the updated decision over the superseded one** at scale.
- **On the unanswerable cell it correctly abstains** (no_conclusion, confidence none) — and naming a
  ruled-out term while abstaining no longer counts as a leak (a grader false-negative the review caught).

## Did it hit the bar?

The targets from [`STRATEGY.md`](STRATEGY.md) §2, and where v1 landed:

| Target | Result |
|---|---|
| ≤5% dead-end error rate | ✅ **0%** |
| high abstention precision (never invent) | ✅ **1.00** (recall 0.89, F1 0.94) |
| ≥3× lower cost than full transcript (medium) | ✅ **6.5×** ($0.075 vs $0.490) |
| ≥10× lower live-context than full transcript | ✅ **25×** (890 vs 22,254 tokens) |
| ≥90% recall accuracy | ⚠️ **85%** overall (93–100% on core decision tasks; fuzzy resolution 69% + buried long-context 64% pull it down) |

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
  Every cost/stress row stores its raw + parsed answer and grade reasons for audit.
- **`decision_status`.** The recall schema distinguishes *settled* / *hypothesis_only* / *open*, so a
  likely-but-unconfirmed cause is reported and flagged rather than forced into a false binary.
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
