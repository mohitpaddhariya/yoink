<p align="center">
  <img src="assets/yoink.png" alt="yoink" width="220">
</p>

<h1 align="center">yoink</h1>

<p align="center"><em>Ask another Claude session what it already figured out — without copy-paste.</em></p>

---

You keep several Claude Code sessions open. One of them already solved the thing you're now stuck on.
**yoink pulls that session's conclusion into your current one** — read-only, in a sentence, for pennies.

## The use case

Yesterday, a session spent an hour tracking down why your deploys hang — it tried three fixes, ruled
them out, and found the real cause. Today you hit the same wall in a fresh session. Redo the hour?
Scroll back through 300 messages and copy-paste? Or just ask:

> **what did my deploy session conclude about the hang?**

```
From deploy-debug · high confidence
Answer:     The release job waits on a DB migration lock that never clears — run the migration out-of-band first.
Ruled out:  the health-check timeout · a slow image pull · the connection-pool size.
```

One sentence back. The hour it spent **ruling things out** is the part you'd most hate to repeat — and
it's exactly what yoink hands you, with the dead ends kept *separate* from the answer.

## yoink vs. doing it by hand

The other session already has the answer. The only question is what it costs *you* to get it. Four ways, and what each actually means:

- **grep the transcript** — keyword-search the raw session log and read the matching lines yourself.
- **read it yourself** — paste the *whole* transcript into your current chat and have the model answer from it.
- **resume it** — reopen the old session with `claude --resume` and ask your question there.
- **yoink** — a cheap, read-only recall step that hands back just the conclusion.

|  | grep the transcript | read it yourself | resume it | **yoink** |
|---|:--:|:--:|:--:|:--:|
| Actually answers the question | ✗ dumps matching lines | ✓ | ✓ | **✓** |
| Cost per question | ~$0 | $0.44 | $0.42 | **$0.07** |
| Tokens dumped into your chat | 48,000 | 22,000 | 42,000 | **~900** |
| Ruled-out dead ends kept *out* of the answer | ✗ | — | — | **✓ 0% leak** |

<sub>Measured over 100 recall tasks + real sessions (`total_cost_usd` and returned tokens). yoink is a
touch slower (~15s vs ~10s) as the recall fork spins up — the win is cost and a clean context. Full
method: [`benchmark/`](benchmark/).</sub>

And the gap widens as the other session gets bigger:

| The other session is… | read it yourself | yoink |  |
|---|--:|--:|:--:|
| small (~5K) | $0.18 | **$0.04** | 5× |
| medium (~25K) | $0.49 | **$0.08** | 6× |
| big (~100K) | $1.70 | **$0.23** | 7× |
| huge (>1M) | won't fit | **just works** | — |

<p align="center"><img src="benchmark/figures/cost.png" alt="cost: read it yourself vs yoink" width="600"></p>

## Why you can trust the answer

A session *tries* things and *rules them out* as it goes. A plain search hands you those dead ends
because the words are right there in the transcript. **yoink reports only the conclusion the session
settled on, and files the abandoned guesses under `ruled out`** — never as the answer.

Measured on 100 recall tasks:

- **89%** overall recall · **0% dead-end leak** — it never once reported a ruled-out guess as the answer
- **100%** on using the *latest* decision (not a superseded one) and on listing what was ruled out
- when no conclusion was reached, it **says so** instead of inventing one (abstention precision **1.00**)

Full numbers, methodology, and graphs: [`benchmark/`](benchmark/).

## Install

```bash
git clone https://github.com/mohitpaddhariya/yoink && cd yoink
uv sync && uv run yoink-install
```

Start a new Claude session — it now reaches for yoink on its own.

<sub>Manual: `claude mcp add --scope user yoink -- uv run --directory "$(pwd)" yoink`</sub>

## Use it

In any Claude session, just ask:

> what did the **&lt;topic&gt;** session conclude about **&lt;x&gt;**?

Or from a terminal:

```bash
uv run yoink-ask --all "deploy" "what was causing the hang?"
```

## How it works

1. You name the session in plain words ("the auth one") — yoink finds it among yours.
2. It re-opens that session's transcript **read-only** and asks your question there.
3. It returns the answer, which session it came from, and any ruled-out dead ends.

It reads the other session's *saved* history, so it never touches a live session and nothing leaves
your machine. If your hint is ambiguous, it shows the top candidates and asks you to pick.

---

<sub>MIT · <code>uv run pytest</code></sub>
