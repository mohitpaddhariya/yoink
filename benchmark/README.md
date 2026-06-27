# yoink cost benchmark

**Is yoink actually cheaper than just letting Claude read the other session's transcript?**
Measured on real Claude sessions — not estimated.

## The two approaches

- **Native** — to answer *"what did the other session conclude?"* Claude must pull that
  session's **entire transcript into your live Opus context**. Cost = transcript tokens ×
  Opus input ($5/MTok). It also bloats your context and, past your window (~1M tokens),
  **overflows — it can't be done at all**.
- **yoink** — a local resolver picks the session (≈0 model tokens), a forked
  `claude -p --resume` recalls in an **isolated, cache-discounted** subprocess (Haiku), and
  only ~**300 tokens** (the answer) enter your context.

## Measured (real sessions)

| Session size | Native (load transcript) | yoink (Haiku recall) | |
|---|---|---|---|
| ~1.8K tok | $0.009 | $0.021 | native cheaper (trivial session) |
| ~6K tok | $0.031 | $0.030 | break-even |
| ~81K tok | $0.41 | **$0.12** | yoink 3.4× |
| ~268K tok | $1.34 | **$0.076** | yoink 18× (warm cache) |
| ~1.4M tok | impossible (overflow) | works | only yoink |

![cost](cost.png)

## Headline

- **Break-even ~5K tokens.** Below that native is cheaper — but you'd just glance at a tiny session.
- **Above ~5K (any real working session) yoink is cheaper, and the gap widens fast** (3×, 18×,
  then native becomes impossible).
- **yoink puts ~300 tokens in your context; native loads the whole transcript** — the consistent
  win, independent of price.
- **Quality holds:** Haiku recall passes the dead-end discrimination gate **10/10** — it still
  tells the ratified conclusion apart from abandoned dead-ends.

## Why yoink wins where it counts

1. **Caching** — resuming a recently-used session hits the prompt cache (~10% of input price).
2. **Cheap model** — recall is extraction; Haiku ($1/$5) is ~5× cheaper than Opus and still passes
   the gate (override with `YOINK_MODEL=claude-opus-4-8` for richer recalls).
3. **Tiny return** — your expensive Opus context only ingests the answer, never the transcript, and
   never overflows.

## Reproduce

```bash
uv run --with matplotlib python benchmark/plot_cost.py   # regenerates cost.png
```

Native = transcript tokens × $5/MTok (Opus input). yoink = measured `total_cost_usd` from the
forked `--resume` recall (Haiku). Dead-end quality: `YOINK_MODEL=claude-haiku-4-5 uv run python eval/run_eval.py`.
