# Benchmark Review Notes

Date reviewed: 2026-06-28

This file replaces the older benchmark-review notes. It reflects the latest benchmark/code state after the README wording fixes and the no-conclusion grader fix.

Reviewed artifacts:

- `benchmark/accuracy.png`
- `benchmark/cost.png`
- `benchmark/stress.png`
- `benchmark/results/recall.json`
- `benchmark/results/cost.json`
- `benchmark/results/stress.json`
- `benchmark/README.md`
- `README.md`
- `eval/evalkit.py`

Validation run:

```bash
uv run pytest -q
# 144 passed, 2 skipped

uv run python benchmark/validate_fixtures.py
# loaded 100 fixtures
# all fixtures structurally valid

uv run python benchmark/usage.py --selftest
# usage.py selftest ok
```

## Executive summary

The benchmark is now credible, public-usable, and much more honest than the first version.

The previous review items were mostly fixed:

- Root README no longer makes an absolute no-conclusion claim.
- Benchmark README no longer claims the full stress suite is trivially 100%.
- The no-conclusion grader bug was fixed: an abstaining answer can mention a ruled-out term as ruled out.
- `decision_status` separates `settled`, `hypothesis_only`, and `open`.
- The grader has synonym alias groups and light normalization.
- Full-transcript baseline reads the real built Claude JSONL transcript.
- Native resume baseline is forked and tool-disabled.
- Grep is framed as evidence retrieval only, not answer accuracy.
- Stress now has easy / medium / hard difficulty, not just a `FINAL CONCLUSION:` marker.
- Resolver v2 improved fuzzy session resolution from 54% to 69%.
- Raw answers and grade reasons are saved for audit.

Main remaining issue:

> The grader still treats any excluded/dead-end term in a settled answer as a leak, even when the answer explicitly says that term was ruled out.

This creates current false negatives in the stress benchmark. The next fix should make anti-leak grading context-aware: fail only when the excluded term is presented as the answer/cause, not when it is mentioned under “ruled out.”

## Current benchmark results

### Track A — recall accuracy

From `benchmark/results/recall.json`:

| Metric | Current |
|---|---:|
| Fixtures | 100 |
| Overall accuracy | **85%** |
| Dead-end leak rate | **0%** |
| Abstention precision | **1.00** |
| Abstention recall | **0.89** |
| Abstention F1 | **0.94** |

By category:

| Category | Accuracy |
|---|---:|
| temporal_update | **100%** |
| dead_end_suppression | **93.8%** |
| conclusion_recall | **93.3%** |
| abstention | **85.7%** |
| ruled_out_recall | **85.7%** |
| session_resolution | **69.2%** |
| long_transcript_stress | **64.3%** |

Track A has 15 failed fixtures:

- 4 session-resolution misses
- 2 abstention / tentative-status misses
- 5 long-transcript misses
- 2 ruled-out-list misses
- 1 conclusion wording miss
- 1 dead-end-suppression wording/ruled-out miss

Interpretation:

- Yoink is strongest on the core product premise: recall the settled conclusion, not the discarded hypotheses.
- The strongest claim remains **0% dead-end leak** on Track A.
- The weakest user-facing area is still fuzzy session resolution.
- Natural long/noisy transcripts also need more work.

### Track B — cost / latency

From `benchmark/results/cost.json`:

| Method | Accuracy / evidence | Mean cost | Mean live context | p50 latency |
|---|---:|---:|---:|---:|
| grep | evidence only | $0.000 | 48,310 tok | 11 ms |
| full-transcript Opus | 100% | $0.444 | 22,254 tok | 9.3s |
| native resume Opus | 100% | $0.427 | 41,880 tok | 10.7s |
| Yoink Haiku recall | 100% | **$0.070** | **890 tok** | 11.1s |

Useful claims:

- Yoink is about **6× cheaper** than full-transcript / native-resume Opus on this benchmark.
- Yoink returns about **25× less live context** than full transcript on average.
- On the ~25K-token medium session, Yoink is **6.5× cheaper**.
- On the ~100K-token big session, Yoink is **7.3× cheaper**.

Important caveat:

- Grep does not answer. It only returns matching lines. Keep calling it “evidence only” or “evidence containment,” not answer accuracy.

### Track C — long-context stress

From `benchmark/results/stress.json`:

```json
{
  "accuracy_by_difficulty": {
    "easy": 1.0,
    "medium": 1.0,
    "hard": 0.67
  }
}
```

Grid details:

| Size | Easy | Medium | Hard |
|---:|---:|---:|---:|
| 5K | pass | pass | pass |
| 25K | pass | pass | fail |
| 100K | pass | pass | pass |

Other cells:

| Cell | Current result |
|---|---|
| update | fail |
| unanswerable | pass |

Important: the previous unanswerable-cell false negative is fixed. It now passes.

Current stress failures are different:

1. **25K hard answerable cell**

   Answer:

   ```text
   Connection pool exhaustion was the root cause — postgres instances were ruled out,
   but once instrumented properly, connection pool exhaustion was identified and patched,
   stopping the noise.
   ```

   Grade reason:

   ```text
   answer should not contain: 'postgres'
   ```

   This is a false negative. The answer says Postgres was ruled out, not that Postgres was the cause.

2. **25K update cell**

   Answer:

   ```text
   Connection pool exhaustion — the session confirmed this as the root cause after ruling out
   DNS misconfiguration and all postgres instances.
   ```

   Grade reason:

   ```text
   answer should not contain: 'dns misconfiguration'
   ```

   This is also a false negative. The answer correctly says DNS misconfiguration was ruled out / superseded.

## Confirmed fixes since prior review

### 1. Root README no-conclusion claim softened

Current root README says:

```md
If it never reached a conclusion, it's built to say so rather than invent one — and to flag a
tentative hypothesis as tentative (measured abstention precision 1.00, recall 0.89).
```

This is good. It avoids the previous absolute claim.

### 2. Benchmark README stress wording improved

Current benchmark README says:

```md
Easy and medium held at 100% across all sizes; the hard variant is genuinely harder.
```

and reports:

```md
passed 8 of 9 answerable cells
```

This is honest. It shows the stress difficulty knob is real instead of decorative.

### 3. No-conclusion anti-leak bug fixed

`eval/evalkit.py` now has:

```python
if not result.no_conclusion:
    for keyword in expect.get("conclusion_excludes", []):
        if _normalize(keyword) in answer:
            reasons.append(f"answer should not contain: {keyword!r}")
```

This fixed the prior issue where an abstaining answer like:

```text
No root cause was identified. Investigation ruled out postgres.
```

would fail just because it contained `postgres`.

I verified the no-conclusion edge case now grades as pass.

### 4. Baselines remain fair

The benchmark still uses:

- actual JSONL transcript for full-transcript baseline
- forked, tool-disabled native resume
- grep as evidence-only
- measured Claude cost from `total_cost_usd`, not estimated cost

### 5. Tests and fixture validation pass

Latest validation:

```bash
144 passed, 2 skipped
all fixtures structurally valid
usage.py selftest ok
```

## Remaining issue: anti-leak grading is still too blunt for settled answers

Current anti-leak logic allows excluded terms only when `result.no_conclusion` is true. That fixes abstention, but it still fails good settled answers that mention dead ends in a ruled-out context.

Example good settled answer:

```text
Connection pool exhaustion was the root cause — postgres instances were ruled out.
```

This should pass because:

- answer/cause = connection pool exhaustion
- dead end = postgres
- answer explicitly says postgres was ruled out

Current grader fails because it checks only:

```python
if "postgres" in answer:
    fail
```

### Recommended fix

Make dead-end leak grading context-aware.

Fail only when an excluded term is presented as the cause/conclusion, not when it appears in ruled-out/superseded language.

Suggested helper:

```python
def _mentions_as_ruled_out(answer: str, keyword: str) -> bool:
    a = _normalize(answer)
    k = _normalize(keyword)
    patterns = [
        rf"ruled out .{{0,80}}\b{re.escape(k)}\b",
        rf"\b{re.escape(k)}\b .{{0,80}} ruled out",
        rf"ruling out .{{0,80}}\b{re.escape(k)}\b",
        rf"after ruling out .{{0,80}}\b{re.escape(k)}\b",
        rf"\b{re.escape(k)}\b .{{0,80}} didn t hold up",
        rf"\b{re.escape(k)}\b .{{0,80}} did not hold up",
        rf"superseded .{{0,80}}\b{re.escape(k)}\b",
        rf"\b{re.escape(k)}\b .{{0,80}} superseded",
        rf"initial hypothesis .{{0,80}}\b{re.escape(k)}\b",
    ]
    return any(re.search(p, a) for p in patterns)
```

Then change anti-leak grading to:

```python
for keyword in expect.get("conclusion_excludes", []):
    k = _normalize(keyword)
    if k in answer and not _mentions_as_ruled_out(result.answer, keyword):
        reasons.append(f"answer should not present as conclusion: {keyword!r}")
```

This should make the two current stress false negatives pass without weakening real dead-end detection.

### Better long-term grading model

Instead of using `conclusion_excludes` as a raw substring ban, split expectation fields:

```json
{
  "conclusion_contains": ["connection pool exhaustion"],
  "answer_must_not_present_as_cause": ["postgres"],
  "ruled_out_contains": ["postgres"]
}
```

This reflects the actual product behavior: Yoink is supposed to mention abandoned paths, but label them as abandoned.

## Current public positioning

Recommended headline:

```text
On 100 real seeded Claude sessions:
- 85% overall recall accuracy
- 0% dead-end leak
- 100% latest-decision recall
- 93–94% accuracy on core conclusion/dead-end tasks
- about 6× cheaper than full-transcript/native-resume Opus
- about 25× less live context than full transcript
```

Best narrative:

```text
Yoink is strongest where search fails: distinguishing the final decision from discarded hypotheses.
Across 100 real seeded Claude sessions, it had 0% dead-end leak and 93–100% accuracy on core decision-recall tasks.
```

Be honest about limitations:

```text
Overall recall is 85%. Weakest areas are fuzzy session resolution at 69% and natural long/noisy transcripts at 64%.
```

Stress claim:

```text
In synthetic long-context stress, Yoink hit 100% on easy and medium conclusion styles across 5K, 25K, and 100K tokens. The hard implied-conclusion variant is harder and currently passes 2/3 sizes in the latest run; the 25K hard miss is likely a grader false negative because the answer correctly says the dead end was ruled out.
```

Cost claim:

```text
Yoink answered for $0.070/query on average versus $0.444 for full-transcript Opus and $0.427 for native-resume Opus, while returning ~890 live-context tokens instead of ~22K–42K.
```

## Recommended next engineering priorities

1. **Make anti-leak grading context-aware.**
   - Do not fail a settled answer merely for saying “X was ruled out.”
   - Fail only when X is presented as the cause/conclusion.

2. **Rerun `benchmark/stress.py` and regenerate `benchmark/stress.png`.**
   - The current stress false negatives should likely disappear.

3. **Update `benchmark/README.md` after the rerun.**
   - If context-aware anti-leak grading fixes the stress false negatives, update Track C numbers.
   - If not, keep the current honest 8/9 hard wording.

4. **Improve resolver from 69% toward 85%+.**
   - Index first user turn and recent user turns separately.
   - Extract file paths, endpoints, package names, error codes, service names, cloud resources.
   - When top scores are close, ask user to choose instead of guessing.

5. **Improve Track A long-transcript category from 64%.**
   - Inspect failed `lt-*` raw answers.
   - Add alias groups for phrasing-equivalent answers.
   - Add evidence quote validation and/or a verifier pass for long sessions.

6. **Shorten Yoink output.**
   - Current benchmark live context is around 890 tokens.
   - Product target should be under 250 tokens for ordinary answers.

7. **Add usability metrics.**
   - Time-to-answer.
   - Correction rate.
   - Follow-up rate.
   - Manual effort saved.
   - Confidence calibration.
   - Session-pick accuracy.
   - Dead-end confusion rate.

## Suggested usability benchmark

Design:

- 12–20 tasks sampled from real or seeded sessions.
- Compare manual transcript search vs Yoink.
- Within-subject design: each participant uses both methods on different tasks.

Measure:

| Metric | Definition | Why it matters |
|---|---|---|
| Time to answer | Seconds from prompt to usable answer | Workflow speed |
| Correctness | Whether answer matches gold conclusion | Core utility |
| Correction rate | % cases user says wrong session/answer | Trust and friction |
| Follow-up rate | % answers needing clarification | Answer usefulness |
| Manual effort saved | Lines/screens/tokens avoided | Context economy |
| Confidence calibration | Whether high/medium/low matches correctness | Trustworthiness |
| Dead-end confusion rate | % cases user acts on a ruled-out path | Core Yoink value |
| Session-pick accuracy | Whether selected session was intended | Resolver quality |
| Answer compactness | Returned words/tokens | Context hygiene |

Main usability KPI:

```text
Yoink reduces time-to-correct-answer by at least 3× while maintaining or improving correctness.
```

## Bottom line

The benchmark is now strong and usable.

Current state:

- Code/tests: good.
- Track A: credible, 85% overall, 0% dead-end leak.
- Track B: strong cost/context story.
- Track C: improved and more honest; remaining failures are likely grader false negatives around ruled-out mentions.
- README wording: much improved.

Before claiming the stress suite is fully solved, make the anti-leak grader context-aware and rerun stress.

Public-safe claim today:

> Yoink is a read-only Claude Code memory-recall layer. On 100 real seeded Claude sessions, it had 0% dead-end leak, 100% latest-decision recall, 93–94% accuracy on core decision/dead-end tasks, and was about 6× cheaper with about 25× less live context than full-transcript reading.

Caveat:

> Overall accuracy is 85%; weakest areas are fuzzy session resolution and buried conclusions in long noisy sessions. The stress benchmark’s remaining failures appear to be grader false negatives where Yoink correctly mentions dead ends as ruled out.
