# Yoink benchmark strategy

Yoink should be benchmarked as a **local Claude Code session-memory recall tool**, not as a coding-agent patch-generation system like SWE-bench.

The core claim to prove:

> Yoink recovers prior Claude Code session conclusions with comparable quality to full-context review, while using far fewer tokens, less human time, and lower cognitive effort.

## 1. Benchmarks to run

### A. Session-conclusion recall benchmark

Measures whether Yoink answers questions about prior sessions correctly.

Task categories:

| Category | What it tests | Example |
|---|---|---|
| Conclusion recall | Finds the final ratified decision | What caused the auth failure? |
| Dead-end suppression | Does not report rejected guesses as current answer | Was Redis the cause? |
| Ruled-out recall | Lists abandoned approaches correctly | What did we rule out? |
| Temporal update | Uses latest conclusion over earlier one | What was the final deployment plan? |
| Abstention | Says no conclusion when the transcript never decided | What did we decide about billing? |
| Session resolution | Finds the right session from a fuzzy hint | the auth session |
| Long transcript stress | Works when evidence is buried in large context | 100K–1M token session |

Recommended benchmark size:

- v1: 100 synthetic fixtures
- v2: 100–200 annotated real Claude Code questions from 30–50 anonymized sessions

Example item:

```json
{
  "id": "auth-token-001",
  "session_hint": "auth session",
  "question": "What did we conclude caused the auth failures?",
  "gold_answer": "The token refresh path reused an expired access token.",
  "gold_ruled_out": ["cache TTL", "network flakiness"],
  "evidence_turn_ids": ["turn_27", "turn_31"],
  "category": "dead_end_suppression",
  "should_abstain": false
}
```

### B. Cost and latency benchmark

Compare Yoink against realistic alternatives.

Baselines:

| Method | Why include it |
|---|---|
| Manual search / scrolling | Real workflow Yoink replaces |
| `rg` / grep over `~/.claude/projects` | Strong cheap local baseline |
| Full transcript into Claude | Accuracy upper bound, expensive baseline |
| Claude native manual resume | Product-adjacent baseline |
| Vector RAG over transcript chunks | Obvious AI-memory architecture baseline |
| Yoink | Proposed system |

Metrics:

| Metric | Definition |
|---|---|
| Accuracy | Correct final answer / total questions |
| Citation accuracy | Cited evidence matches gold turn(s) |
| Abstention F1 | F1 for `no_conclusion=true` decisions |
| Dead-end error rate | Rejected path presented as current answer |
| p50 / p95 latency | Wall-clock response time |
| Tokens/query | Total model input + output tokens |
| Cost/query | USD cost per question |
| Live-context added | Tokens inserted back into current chat |
| Overflow rate | Full-context baseline cannot fit transcript |

Suggested public table:

| Method | Accuracy ↑ | Citation acc. ↑ | Abstention F1 ↑ | Dead-end error ↓ | p50 latency ↓ | Tokens/query ↓ | Cost/query ↓ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Manual search |  |  |  |  |  |  |  |
| `rg` search |  |  |  |  |  |  |  |
| Full transcript Claude |  |  |  |  |  |  |  |
| Vector RAG |  |  |  |  |  |  |  |
| Yoink |  |  |  |  |  |  |  |

### C. Long-context stress benchmark

Synthetic conclusion-in-haystack tests.

Vary:

- transcript size: 5K, 25K, 100K, 500K, 1M tokens
- evidence position: beginning, middle, end
- distractor count: 0, 3, 10 rejected alternatives
- conclusion updates: old decision later overwritten
- unanswerable questions: no valid conclusion exists

Report accuracy and cost by transcript length. A heatmap works well.

### D. Usability benchmark

Run a small within-subject developer study.

Participants:

- 8–12 developers for v1
- ideally Claude Code or AI coding assistant users

Conditions:

1. Manual search / `rg`
2. Yoink
3. Optional: full transcript Claude

Tasks:

- 6–10 recall questions per participant
- counterbalance ordering to reduce learning effects

Primary usability metrics:

| Metric | Definition |
|---|---|
| Task completion time | Seconds from question shown to submitted answer |
| Task success | Correct answer + no dead-end leak + correct source |
| UMUX-LITE | 2-question usability score |
| NASA-TLX effort/frustration | Lightweight workload measure |
| Preference | Which method would the user choose again? |

Recommended UMUX-LITE questions, 1–7 Likert:

1. Yoink's capabilities meet my requirements.
2. Yoink is easy to use.

Recommended public table:

| Method | Task success ↑ | Median human time ↓ | UMUX-LITE ↑ | Effort ↓ | Frustration ↓ |
|---|---:|---:|---:|---:|---:|
| Manual search |  |  |  |  |  |
| `rg` search |  |  |  |  |  |
| Yoink |  |  |  |  |  |

## 2. Success criteria

Good initial targets:

- ≥90% accuracy on synthetic recall fixtures
- ≥85% accuracy on real annotated recall questions
- ≤5% dead-end error rate
- high abstention precision: avoid inventing conclusions
- ≥3× lower cost than full transcript for medium sessions
- ≥10× lower live-context usage than full transcript
- lower median human task time than manual search
- UMUX-LITE >70/100 or clear preference over manual search

## 3. Public positioning

Do not claim Yoink is a better coding agent. Claim:

> Yoink is a local, read-only memory recall layer for Claude Code sessions.

Strong README claims to aim for:

- Yoink recovered prior-session conclusions with X% accuracy across Y annotated Claude Code recall tasks.
- Yoink reduced live-context load by X× compared with full transcript loading.
- Yoink reduced median human recall time from A seconds to B seconds versus manual search.
- Yoink reduced dead-end errors by X% versus keyword search.
- Developers preferred Yoink over manual search in N/N tasks.

## 4. References to cite

Useful benchmark inspirations:

- LongMemEval: long-term memory evaluation with extraction, temporal reasoning, knowledge updates, and abstention.
- LoCoMo: long conversational memory benchmark with evidence turn IDs.
- RULER: long-context retrieval stress tests beyond simple needle-in-haystack.
- LOFT: long-context vs retrieval/RAG comparison with cost/latency framing.
- Mem0: memory-system benchmark using accuracy, token consumption, and p95 latency.
- SWE-bench: cite only to explain why Yoink is not a patch-generation benchmark.
- SUS: Brooke 1996 usability scale.
- UMUX-LITE: Lewis, Utesch, Maher 2013 lightweight usability metric.
- NASA-TLX: Hart & Staveland 1988 workload metric.
