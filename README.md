# yoink

> Grab focused context from another Claude session, without copy-paste.

You run several Claude Code sessions at once. Each builds its own working context — files it
checked, what it ruled out, what you clarified, its conclusion. When one session needs what another
already worked out, you window-switch, scroll, copy, paste, re-explain.

**yoink** lets you ask, in plain language, *"what did the session that debugged auth conclude about
token refresh?"* and get a focused, provenance-tagged answer drawn from that session's recorded work.

## What it is — and what it is NOT

- **It IS:** asking another Claude session's **recorded working context**. yoink resumes that
  session's on-disk transcript in a fresh, forked, read-only process and answers from it.
- **It is NOT:** talking to or injecting into a live terminal. The other session is never touched.
  Answers come from the last persisted turn, so they lag a live session by at most the in-flight turn.

Think of it as *asking the peer's notes*, not interrupting the peer.

## Status

MVP, in development — **Claude → Claude, localhost only**. Cross-agent (Codex), remote sharing, and
live in-memory messaging are deferred. See [`.claude/plan.md`](.claude/plan.md) for the full design.

## Install (once)

```bash
uv sync
claude mcp add yoink -- uv run --directory "$(pwd)" python broker.py
```

Then in any Claude session: *"yoink what the auth session concluded about X."*

## Develop

```bash
uv sync            # create the environment
uv run pytest      # run the test suite
uv run python broker.py --health   # verify the answerer CLI flags + a smoke resume
```

Built with [FastMCP](https://github.com/jlowin/fastmcp), managed with [uv](https://docs.astral.sh/uv/).
