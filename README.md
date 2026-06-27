<p align="center">
  <img src="assets/yoink.png" alt="yoink" width="240">
</p>

<h1 align="center">yoink</h1>

<p align="center"><em>It already figured this out. Just ask it.</em></p>

<p align="center">
recalls the answer, not the whole transcript · a paragraph back, not the transcript · 3–7× cheaper than reading it yourself · read-only, never interrupts
</p>

---

You've got five Claude sessions open. One of them already debugged the auth bug an hour ago. To use
that now, you switch windows, scroll back, copy, paste, and explain it all over again — and half the
time you just redo work that was already done.

yoink lets you ask, in plain words:

> **what did my auth session conclude about the token bug?**

and the other session answers — with the conclusion it actually landed on.

## The trick: it knows what a session *decided*, not just what it *said*

Ask about a real session:

> **what did my staging session conclude about how to access the server?**

```
From staging-deploy · high confidence
Answer:    It's on EC2, dashboard at staging.example.internal, admin access is the VPN only.
Ruled out: SSH (the firewall blocks it) → use the VPN.  Kafka (there isn't any) → it's Redis.
```

That session *tried* SSH and *tried* Kafka, hit walls, and moved on. yoink gives you what it **settled
on** — and files the abandoned guesses under **ruled out**. A plain search over the transcript would
have handed you "SSH" and "Kafka," the dead ends, just because the words are there.

That's the whole point: **yoink tells you what a session decided, not everything it tried.**

## Cheaper than reading the transcript yourself

<p align="center"><img src="benchmark/cost.png" alt="cost: native vs yoink" width="620"></p>

Reading the other session "by hand" means loading its **whole transcript** into your chat — it's
expensive, it clutters your context, and on a big session it simply doesn't fit. yoink reads it in a
separate, cheap step and hands back a paragraph.

| The other session is… | Read it yourself | yoink |
|---|---|---|
| small (~5K) | $0.18 | **$0.04** |
| medium (~25K) | $0.50 | **$0.08** |
| big (~100K) | $1.71 | **$0.23** |
| huge (>1M) | won't fit | **just works** |

<sub>"Read it yourself" = a model reads the whole transcript (Opus) to answer; "yoink" = the Haiku recall. Measured `total_cost_usd`, both. yoink also hands back ~700 tokens instead of the whole transcript.</sub>

## How it works

1. You describe the session ("the auth one"). yoink finds it among your sessions.
2. It re-opens that session's notes **read-only** and asks your question there.
3. It hands you the answer, says which session it came from, and lists any dead ends.

## Install

```bash
git clone https://github.com/mohitpaddhariya/yoink && cd yoink
uv sync && uv run yoink-install
```

That sets it up and tells Claude to reach for it on its own. Start a new Claude session and you're done.

<sub>Prefer manual? `claude mcp add --scope user yoink -- uv run --directory "$(pwd)" yoink`</sub>

## Use it

Just ask, in any Claude session:

> what did the &lt;topic&gt; session conclude about &lt;x&gt;?

Or from a terminal:

```bash
uv run yoink-ask --all "staging" "how do I access the server?"
```

## Good to know

- **It reads, it never interrupts.** yoink looks at the other session's saved history. It never touches
  the session you have running — the answer is from its last saved moment.
- **It shows its work.** Which session, how confident. Trust it, or correct it.
- **If it never reached a conclusion, it says so.** It won't invent one.

## FAQ

**Does it talk to my live session?** No — it reads the saved notes, read-only.

**Which sessions can it see?** All of yours, on your machine. Nothing leaves your laptop.

**What if it grabs the wrong session?** It tells you which one it used; if your hint is ambiguous it
asks you to pick.

**Does it actually work?** Across 100 recall tasks, yoink never once reported a ruled-out dead end as
the answer, and never invented a conclusion when a session hadn't reached one. See `benchmark/`.

**Is "cheaper" real?** Measured on real sessions, both ways. See `benchmark/`.

---

<sub>MIT · `uv run pytest` to run the tests</sub>
