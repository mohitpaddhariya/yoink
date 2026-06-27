# yoink

> Grab focused context from another Claude session, without copy-paste.

You run several Claude Code sessions at once. Each builds its own working context — files it
checked, what it ruled out, what you clarified, its conclusion. When one session needs what another
already worked out, you window-switch, scroll, copy, paste, re-explain.

**yoink** lets you ask, in plain language — *"yoink what the auth session concluded about token
refresh"* — and get a focused, provenance-tagged answer drawn from that session's recorded work.

## What it is — and what it is NOT

- **It IS:** asking another Claude session's **recorded working context**. yoink resumes that
  session's on-disk transcript in a fresh, forked, **read-only** process and answers from it.
- **It is NOT:** talking to or injecting into a live terminal. The other session is never touched.
  Answers come from the last persisted turn, so they lag a live session by at most the in-flight turn.

Think of it as *asking the peer's notes*, not interrupting the peer.

## How it works

```
ask_recorded_session(peer_hint, question)          # the one MCP tool
  └─ resolver.resolve(...)        → ranked candidate sessions + a source_match
        ├─ no match / low         → "no match" or a pick-one disambiguation (no answerer call)
        └─ high / medium          → best candidate
              recall_prompt = prompts.build_recall_prompt(question)
              answerer.run_answerer(session_id, target_project_cwd, recall_prompt)
                 └─ claude -p --resume <id> --fork-session --permission-mode plan
                    --tools "" --disallowedTools "mcp__*" --strict-mcp-config   (recall-only)
                 └─ prompts.parse_answer(.result)  → RecallAnswer
              provenance.format_provenance(best, source_match, answer)
```

The **recall-only guarantee** is enforced at the tool layer, not just the prompt: the resumed
process runs with `--tools ""` (no built-in tools) and `--disallowedTools "mcp__*"`, so it
physically cannot re-investigate — it can only recall. `--fork-session` keeps the peer's real
history byte-for-byte untouched. `broker.py --health` is the hard gate that verifies this (it
asserts the resumed process loaded **zero** tools).

## Install

```bash
uv sync
claude mcp add yoink -- uv run --directory "$(pwd)" python broker.py
uv run python broker.py --health     # verify the recall-only flags work end-to-end
```

Then in any Claude session, just ask in natural language:

> *yoink what the auth-debugging session concluded about the token refresh bug*

## How answers are shaped

- **Two confidences, never collapsed:** `source match` (did yoink pick the right session?) and
  `answer confidence` (did that session actually reach a clear conclusion?).
- **Compact provenance** by default:
  `From auth-debugging · payments · 4m ago · source match: high · answer confidence: medium`
- **Dead-end safety:** the prompt biases to the most-recent *ratified* conclusion and lists abandoned
  paths as ruled-out — it never resurfaces a ruled-out guess as the answer.
- **Safe failure:** if the session never concluded, yoink says so and lists what it *did* contain —
  it never invents a confident answer.
- **Source-match thresholds:** high → answer; medium → answer **plus a confirm-before-changes note**;
  low → show the top 2–3 sessions to pick from (never a silent guess).

## Scope & limitations

- **Claude → Claude, localhost only.** Cross-agent (Codex), remote sharing, and live in-memory
  messaging are deferred — see [`.claude/plan.md`](.claude/plan.md) and the roadmap there.
- Discovery reads `~/.claude/projects/**/*.jsonl` **lightly and defensively** (titles + recency);
  that JSONL format is internal and may change between Claude Code versions, so discovery degrades
  rather than crashes. Answering only ever goes through the official `claude -p --resume` interface.
- Default-deny across repos: yoink only scans the caller's project unless cross-project is opted in.

## Development

```bash
uv sync                            # create the environment
uv run pytest                      # fast, offline unit suite
uv run python run_eval.py          # the dead-end correctness gate (live model calls)
YOINK_INTEGRATION=1 uv run pytest tests/test_integration.py   # live end-to-end
```

The **dead-end gate** (`run_eval.py` + `fixtures/`) is the make-or-break test: it proves the recall
prompt extracts the *ratified* conclusion from messy transcripts (wrong-then-right, flip-flops, user
corrections, no-conclusion, two-issues, …) rather than a dead end.

## Layout

```
yoink/
├── prompts.py        # recall prompt + lenient/total answer parser (RecallAnswer)
├── resolver.py       # session discovery: topic+recency ranking, fork/self exclusion, cwd guard
├── answerer.py       # the verified claude -p --resume subprocess + typed errors + smoke gate
├── provenance.py     # pure formatting: two confidences, safe failure, thresholds
├── broker.py         # yoink FastMCP server (ask_recorded_session) + --health
├── evalkit.py        # dead-end fixture loading + deterministic grading
├── run_eval.py       # the dead-end correctness gate (live)
├── fixtures/         # ≥10 dead-end scenarios
├── tests/            # unit suite + gated live integration
└── .claude/          # plan.md (source of truth) + build-spec.md
```

Built with [FastMCP](https://github.com/jlowin/fastmcp), managed with [uv](https://docs.astral.sh/uv/).
