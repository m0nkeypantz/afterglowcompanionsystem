# Afterglow Companion System

Afterglow is a companion memory, recall, emotional state, diary, pulse, and OpenClaw plugin suite for companion agents.

It is designed as a blank-state public package. It does not ship private memories, private companion personality, credentials, user names, phone bridges, or live deployment paths.

## What It Provides

- Local SQLite memory database with FTS recall.
- Importers for OpenClaw sessions/local memory files and Hindsight JSON exports.
- Semantic fact promotion for durable facts.
- Fast recall and deep recall tools.
- `turn_context.py` for pre-message prompt injection.
- Cross-session digest and recall from recent OpenClaw sessions.
- Emotional state stored in `brain/soul_state.json` and rendered to prompt-safe markdown.
- Autonomous pulse loop that updates drives and writes diary entries.
- Fallback ingestion daemon that keeps indexing sessions if a hook misses a message.
- Browser UI for memory stats, recall search, diaries, emotional gauges, and pulse state.
- OpenClaw plugin that wires the system into `before_prompt_build`, `message_received`, and `message_sending`.

## Quick Start

From this repository:

```powershell
python .\scripts\setup_afterglow.py
```

The installer asks for:

- OpenClaw state directory, usually `~\.openclaw`
- OpenClaw workspace, usually `~\.openclaw\workspace`
- companion/user display names
- model choices for pulse, diary, and reflection jobs
- whether to import existing OpenClaw memory now
- optional Hindsight export JSON path

Non-interactive example:

```powershell
python .\scripts\setup_afterglow.py `
  --state-dir "$HOME\.openclaw" `
  --workspace "$HOME\.openclaw\workspace" `
  --companion-name "Companion" `
  --user-name "User" `
  --pulse-model "openrouter/deepseek/deepseek-v4-flash" `
  --diary-model "openrouter/deepseek/deepseek-v4-flash" `
  --enable-pulse `
  --import-openclaw `
  --non-interactive
```

Then restart OpenClaw.

## Common Commands

```powershell
# Check database health
python "$HOME\.openclaw\workspace\scripts\afterglow.py" summary

# Deep recall
python "$HOME\.openclaw\workspace\scripts\memory_recall_tool.py" "important relationship preferences" --expand

# Build the same context the plugin injects before a message
python "$HOME\.openclaw\workspace\scripts\turn_context.py" "current task and recent context" --compact

# Start browser UI
python "$HOME\.openclaw\workspace\scripts\ui_server.py"

# Run one pulse now
python "$HOME\.openclaw\workspace\scripts\pulse.py" --force
```

## Hindsight Import

Export Hindsight to JSON first, then run:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-hindsight ".\hindsight-export.json" --promote-facts --fact-limit 10000
```

Afterglow imports additively. It does not delete source files or overwrite the export.

## Scheduler Helpers

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.openclaw\workspace\scripts\install_windows_tasks.ps1"
```

Linux/systemd user services:

```bash
bash "$HOME/.openclaw/workspace/scripts/install_systemd_user.sh"
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Setup](docs/SETUP.md)
- [OpenClaw Integration](docs/OPENCLAW_INTEGRATION.md)
- [Migration](docs/MIGRATION.md)
- [Pulse and Emotion](docs/PULSE_AND_EMOTION.md)
- [Browser UI](docs/UI.md)
- [Privacy](docs/PRIVACY.md)

## Safety Defaults

The public package disables OpenClaw native memory tools and uses Afterglow as the live memory path. It also keeps proactive outreach disabled by default. Pulse jobs can write diary entries and draft internal actions, but they do not send messages unless the user wires an outbound integration and enables it.
