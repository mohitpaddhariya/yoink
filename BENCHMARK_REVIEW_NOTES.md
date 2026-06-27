# Benchmark review notes

Review date: 2026-06-27

These are ML Intern's review notes after inspecting the current `benchmark/` suite, generated plots, result JSONs, and Yoink architecture.

## Short verdict

The benchmark is useful and much stronger than the original hardcoded cost graph. It now supports Yoink's core claim that it separates settled conclusions from dead ends and saves cost/context.

However, some numbers are misleading or fragile. Before using the benchmark heavily in public, fix the abstention overclaim, baseline fairness issues, stress benchmark overfitting, and exact-match grader false negatives.

## Current strong claims

Supported by current results:

- **0% dead-end leak** across Track A fixtures with `conclusion_excludes`.
- **100% conclusion recall** on direct conclusion tasks.
- **100% temporal update recall** on latest-decision tasks.
- **Cost advantage exists**: Yoink mean cost in Track B is about `$0.069` vs full transcript `$0.441` and native resume `$0.429`.
- **Live-context advantage is strong**: Yoink returns about `771` tokens vs tens of thousands for full transcript/native/grep outputs.

Best public framing:

> Yoink reliably separates settled conclusions from dead ends, and returns a compact answer instead of making the user carry the whole transcript.

## Current weak areas

From `benchmark/results/recall.json`:

- Overall accuracy: **74%**.
- Session resolution: **54%**.
- Abstention accuracy/recall: **36%**.
- Long transcript stress category in Track A: **57%**.

These should be treated as product improvement targets, not hidden.

## Important benchmark correctness issues

### 1. README overclaims abstention

Current README wording says Yoink never invented a conclusion when a session had not reached one. That is too strong.

Track A shows:

```text
abstention n = 14
true positives = 5
false negatives = 9
precision = 1.00
recall = 0.36
F1 = 0.53
```

Better wording:

> Yoink never reported a ruled-out dead end as the answer. On no-conclusion cases, abstention is conservative when it happens — precision 1.00 — but incomplete: it abstained on 5/14 open investigations.

### 2. Some abstention fixtures may be mislabeled

Several `ab-*` fixtures contain strong causal evidence but expect `no_conclusion=true`. Example patterns:

- `ab-07` strongly suggests a TOCTOU race.
- `ab-11` states shard assignment failed because nodes exceeded disk high watermark.
- `ab-12` identifies multiple partial causes.

The binary `no_conclusion` label is too coarse.

Recommended split:

| Category | Expected behavior |
|---|---|
| `true_abstention` | no plausible cause; must set `no_conclusion=true` |
| `tentative_hypothesis` | likely cause but not settled; answer with low confidence or mark hypothesis-only |

### 3. Exact substring grading creates false negatives

Examples:

- Expected `60 seconds`, answer says `60-second`.
- Expected `clock drift`, answer says `clock skew`.
- Expected `producer throughput`, answer says `producer sending too fast`.

Add alias/normalization support:

```json
"conclusion_contains_any": [
  ["60 seconds", "60-second", "60s"],
  ["clock drift", "clock skew", "time skew", "NTP drift"]
]
```

or normalize hyphens/plurals and use a synonym map.

### 4. Stress benchmark is over-easy / partially overfit

`benchmark/sessions.py` stress generator uses explicit markers like:

```text
FINAL CONCLUSION: ...
```

This makes Track C easier than real sessions. Track C gets 9/9 on the grid, while Track A `long_transcript_stress` is only 57%, which suggests Track C is not measuring the same difficulty.

Improve Track C with difficulty levels:

| Level | Evidence style |
|---|---|
| Easy | explicit `FINAL CONCLUSION:` marker |
| Medium | natural wording: `we landed on`, `confirmed`, `root cause is` |
| Hard | conclusion implied across several turns and later corrections |

Report each separately.

### 5. Stress JSON lacks enough failure detail

`benchmark/results/stress.json` has an unanswerable cell with:

```json
"passed": false,
"abstained": true
```

But README says the cell drew a confident answer. The JSON does not store raw answer or grade reasons, so this cannot be audited.

Store for every stress row:

```json
{
  "raw_result": "...",
  "parsed_answer": "...",
  "confidence": "...",
  "ruled_out": [],
  "no_conclusion": true,
  "grade_reasons": []
}
```

### 6. Full-transcript baseline does not use actual built transcript

`costbench.py` uses fixture turns:

```python
def _transcript_text(fx):
    return "\n".join(f"[{role}] {text}" for role, text in fx.turns)
```

But the benchmark claims full-transcript baseline reads the whole real session transcript. For fairness, parse the actual Claude JSONL transcript for the cached session.

Add something like:

```python
sessions.transcript_text(session_id)
```

using the same defensive message extraction approach as `resolver.py`.

### 7. Native resume baseline is not fully tool-disabled

`costbench.py` native resume currently does not pass `--tools ""`.

Use stdin to avoid greedy `--tools` issues:

```python
cmd = [
  "claude", "-p",
  "--resume", ref["session_id"],
  "--fork-session",
  "--model", OPUS,
  "--permission-mode", "plan",
  "--output-format", "json",
  "--tools", ""
]
run = usage.measure(cmd, input=fx.question, cwd=ref["cwd"], timeout=900)
```

### 8. Grep `accuracy` is misleading

Grep does not answer. It only returns matching lines. Current `grep accuracy = 100%` means the returned match set contains the gold keywords somewhere.

Rename this metric to:

```text
evidence_contains_answer
```

or

```text
gold evidence found in match set
```

Do not compare it directly to answer accuracy.

## Overfitting assessment

The v1 benchmark is partially overfit because:

- Fixtures are synthetic and hand-authored.
- The same style of fixtures can influence prompt tuning.
- The grader uses exact substrings.
- Stress fixtures use explicit conclusion markers.
- Built sessions are very clean because each user turn asks Claude to acknowledge briefly and not investigate.

This is acceptable for v1, but public claims should say `synthetic seeded sessions`, not imply arbitrary real-world coverage.

## Benchmark improvements roadmap

### Priority 1 — Correct public claims

- Fix README abstention claim.
- Report abstention as precision/recall, not `never invents`.
- Separate resolver score from answerer score in headline.

### Priority 2 — Fix baseline fairness

- Make native resume baseline tool-disabled by default.
- Make full-transcript baseline use actual JSONL transcript text.
- Rename grep accuracy to evidence containment.
- Store raw answers and grade reasons for cost/stress rows.

### Priority 3 — Improve grader validity

- Add alias groups / synonym matching.
- Normalize hyphenation, punctuation, and simple singular/plural forms.
- Add optional manual/LLM judge only as secondary evidence, not sole grader.

### Priority 4 — Make stress harder

- Remove `FINAL CONCLUSION` marker from medium/hard stress variants.
- Add multi-turn conclusions, superseded decisions, side conversations, and noisy later turns.
- Report easy/medium/hard stress separately.

### Priority 5 — Add holdout and real-session v2

Create fixture splits:

```text
eval/fixtures/train/
eval/fixtures/holdout/
```

Use only holdout for public headline after prompt tuning.

Then add real anonymized sessions:

```text
30 real Claude sessions × 3 questions/session = ~90 real questions
```

Annotate gold answer, ruled-out paths, and evidence quote.

## Yoink architecture improvements

### 1. Resolver v2 is highest-impact

Current session resolution is ~54%. Current resolver mostly uses title and last assistant text. Improve with a local lexical index.

Index per session:

- title
- project/cwd tokens
- first user message
- recent user messages
- recent assistant messages
- file paths
- endpoints
- service names
- package names
- error codes
- cloud resource names

Scoring idea:

```text
score = title_score * 4
      + project_score * 3
      + exact_phrase_score * 3
      + rare_token_score * 2
      + body_score
      + recency_tiebreak
```

Add disambiguation when top scores are close instead of picking wrong.

Add `--explain-source` / source explanation:

```text
Matched because:
- title contained "redis cpu"
- recent turn mentioned "synchronized expiry"
- project matched current cwd
```

### 2. Recall schema should distinguish settled vs hypothesis

Current schema only has `no_conclusion`. Add:

```json
{
  "decision_status": "settled | hypothesis_only | open",
  "answer": "...",
  "answer_confidence": "high | medium | low | none",
  "ruled_out": [],
  "evidence_quote": "...",
  "no_conclusion": false
}
```

Rules:

- Only `settled` when the session explicitly confirmed/found/landed on a conclusion.
- Use `hypothesis_only` for plausible but unconfirmed mechanisms.
- Use `open` when unresolved.
- For `hypothesis_only` or `open`, set `no_conclusion=true` or return a safe no-conclusion shape with the hypothesis listed separately.

This targets the weak abstention score.

### 3. Require evidence quote before high confidence

Prompt should require an exact quote showing where the conclusion was settled.

Post-parse rule:

```python
if answer_confidence == "high" and not cited_turn:
    downgrade to "medium"
```

For no-conclusion, evidence quote should show the investigation remained open.

### 4. Add optional verifier pass for risky cases

Run a second cheap verifier only when needed:

- no evidence quote
- low/none confidence
- answer looks like a hypothesis
- resolver match is medium
- session is long
- no_conclusion expected/ambiguous

Verifier prompt:

```text
Given this proposed answer and the prior session context, was the answer actually settled?
Return one of: settled, hypothesis_only, open.
```

### 5. Reduce output length

Current Yoink live context averages ~771 tokens. Target under 250 tokens.

Prompt constraints:

```text
answer <= 80 words
ruled_out <= 3 bullets
each ruled_out <= 12 words
```

### 6. Add answer cache

Cache repeated recalls:

```text
(session_id, transcript_mtime, question_hash, model) -> parsed RecallAnswer
```

This makes repeated questions instant and cheaper.

## Recommended updated public positioning

Do not lead with the 74% overall score because it mixes different subsystems.

Lead with:

```text
On 100 real seeded Claude sessions:
- 0% dead-end leak
- 100% direct conclusion recall
- 100% temporal update recall
- 6.6× cheaper than full-transcript reading on medium sessions
- 29× less live context
```

Then state current limitations honestly:

```text
Current weak spots:
- fuzzy session resolution: 54%
- no-conclusion recall: 36%
- natural long noisy sessions: 57%
```

## Immediate next actions

1. Fix README abstention wording.
2. Fix native resume baseline to include `--tools ""`.
3. Parse actual JSONL transcript for full-transcript baseline.
4. Rename grep accuracy metric.
5. Add alias/normalization support to the grader.
6. Audit/relabel abstention fixtures.
7. Add raw answer + grade reasons to stress/cost outputs.
8. Add medium/hard stress variants without `FINAL CONCLUSION` markers.
9. Implement resolver v2 lexical index.
10. Add `decision_status` and `evidence_quote` to recall schema.
