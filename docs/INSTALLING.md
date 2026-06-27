# Installing yoink

yoink is a local MCP server. It reads your Claude transcripts under
`$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`) and recalls another session's
conclusion on demand — read-only, with provenance.

## Prerequisites

- The `claude` CLI on your PATH, logged in.
- [uv](https://docs.astral.sh/uv/).

## One-command setup (recommended)

```bash
git clone https://github.com/mohitpaddhariya/yoink && cd yoink
uv sync
uv run yoink-install
```

The installer:

1. asks for the **recall model** — default `claude-haiku-4-5` (cheapest; passes the dead-end gate
   10/10), or `claude-sonnet-4-6` / `claude-opus-4-8` for richer recalls — and saves it to
   `~/.config/yoink/config.json`;
2. registers the MCP server (`claude mcp add --scope user yoink -- …`);
3. patches your CLAUDE.md with an auto-use rule, so Claude reaches for yoink **instead of native
   transcript search** (you don't have to say "yoink" every time);
4. runs the recall-only health check.

Non-interactive / scripted:

```bash
uv run yoink-install --model claude-haiku-4-5 --scope user --yes
```

Flags: `--model <id>`, `--scope user|local`, `--claude-md <path>`, `--no-mcp`, `--no-claude-md`, `--yes`.

## Manual setup

```bash
uv sync
claude mcp add --scope user yoink -- uv run --directory "$(pwd)" yoink
uv run yoink --health        # expect: OK: …
```

Then add this to your global CLAUDE.md (`$CLAUDE_CONFIG_DIR/CLAUDE.md`) so it triggers automatically:

> When the user asks what a different or earlier Claude session concluded/decided/found — or when
> answering would mean reading another session's transcript — use the `ask_recorded_session` (yoink)
> tool instead of a native search.

## Configuration

`~/.config/yoink/config.json` (or set `$YOINK_CONFIG` to relocate it):

```json
{ "model": "claude-haiku-4-5", "timeout": 120 }
```

Environment overrides (win over the file): `YOINK_MODEL`, `YOINK_TIMEOUT`. The transcript location
follows `CLAUDE_CONFIG_DIR` automatically.

## Using it

- **In a Claude session:** start a **new** session (MCP servers load at startup), then ask naturally —
  *"what did the auth session conclude about token refresh?"* Confirm it's loaded with `/mcp`.
- **From the terminal:** `uv run yoink-ask --all "<topic>" "<question>"`.
- **Health:** `uv run yoink --health`.

## Uninstall

```bash
claude mcp remove yoink
rm -f ~/.config/yoink/config.json
# delete the yoink:begin … yoink:end block from your CLAUDE.md
```
