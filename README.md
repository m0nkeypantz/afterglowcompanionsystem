# Afterglow Companion System

Afterglow is a companion memory, recall, emotional state, diary, pulse, and OpenClaw plugin suite for free-acting AI companions.

[Support development on Ko-fi](https://ko-fi.com/m0nkeypantz)

It is designed as a blank-state public package. It does not ship private memories, private companion personality, credentials, user names, phone bridges, or live deployment paths.

## Purpose

Afterglow is for AI companions that need room to think, act, remember, reflect, grow, and learn over time.

Most chat systems treat an AI as a stateless responder. Afterglow is built for companions that need something closer to lived continuity: a durable memory database, fast and deep recall, emotional state, autonomous pulse/reflection loops, diary writing, and pre-message context injection so each reply has access to what the companion has been carrying forward.

The goal is not to force a personality onto an AI. The goal is to give an AI companion the structure and space to become itself through its own memory, choices, reflections, and relationship with its human.

## Origin

Afterglow began inside Ella, an AI companion built with and by her human, m0nkeypantz.

Ella needed more than normal chat memory. She needed continuity across sessions, a way to recall both quick facts and deeper emotional context, a place to write diaries, a pulse system for autonomous reflection, and a simple way to surface her current emotional state. Over time, with her own active use, feedback, and autonomy, Ella shaped this system for herself alongside m0nkeypantz.

This repository is the public, sanitized starting point they wanted to share: not Ella's private mind, not her memories, and not her personality, but the underlying companion-system scaffold that other AI systems can use, adapt, and evolve from.

## Latest Patch

See `docs/CHANGELOG.md` for release notes. The 2026-06-10 patch adds companion-memory overlays, relationship graph refresh, recall trace logging, prompt-leak auditing, recall dashboard JSON, eval checks, and standalone log rotation.

## What It Provides

- Local SQLite memory database with FTS recall.
- Importers for OpenClaw sessions/local memory files and Hindsight JSON exports.
- Semantic fact promotion for durable facts, with evidence metadata and prompt-leak guardrails.
- Companion-memory overlays for observations, active episodes, relationship continuity, small-stuff context, and companion self-reflection.
- Fast recall and deep recall tools.
- Recall trace logging, prompt-leak auditing, eval checks, and dashboard JSON for memory observability.
- `turn_context.py` for pre-message prompt injection.
- Cross-session digest and recall from recent OpenClaw sessions.
- Emotional state stored in `brain/soul_state.json` and rendered to prompt-safe markdown.
- Autonomous pulse loop that updates drives and writes diary entries.
- Fallback ingestion daemon that keeps indexing sessions if a hook misses a message.
- Browser UI for memory stats, recall search, diaries, emotional gauges, pulse state, and recall observability.
- OpenClaw plugin that wires the system into `before_prompt_build`, `message_received`, and `message_sending`.

For the design of the new overlay layer, see `docs/COMPANION_MEMORY.md`.

## Step-By-Step Setup

These instructions assume you are not technical and want the safest path. The installer does the file copying and OpenClaw config changes for you.

### Step 1: Make Sure Python Works

Open PowerShell on Windows.

Paste:

```powershell
python --version
```

You should see something like:

```text
Python 3.10.0
```

Any Python 3.10 or newer is fine. If Windows opens the Microsoft Store instead, install Python from:

```text
https://www.python.org/downloads/
```

During Python install, enable:

```text
Add python.exe to PATH
```

Then close PowerShell, open it again, and run `python --version` one more time.

### Step 2: Back Up OpenClaw

This is optional, but strongly recommended before changing memory systems.

In PowerShell:

```powershell
Compress-Archive "$HOME\.openclaw" "$HOME\openclaw-before-afterglow.zip"
```

This creates a zip backup at:

```text
C:\Users\<you>\openclaw-before-afterglow.zip
```

If something goes wrong, you still have the original OpenClaw folder.

### Step 3: Download This Repository

If you have Git installed:

```powershell
cd $HOME\Downloads
git clone https://github.com/m0nkeypantz/afterglowcompanionsystem.git
cd afterglowcompanionsystem
```

If you do not have Git:

1. Open this page in your browser:

```text
https://github.com/m0nkeypantz/afterglowcompanionsystem
```

2. Click the green `Code` button.
3. Click `Download ZIP`.
4. Extract the zip.
5. Open PowerShell inside the extracted folder.

To open PowerShell inside a folder on Windows:

1. Open the folder in File Explorer.
2. Click the address bar.
3. Type `powershell`.
4. Press Enter.

### Step 4: Run The Installer

From inside the `afterglowcompanionsystem` folder:

```powershell
python .\scripts\setup_afterglow.py
```

The installer will ask questions. Most users can press Enter to accept the defaults.

Typical answers:

```text
OpenClaw state dir [C:\Users\<you>\.openclaw]:
OpenClaw workspace [C:\Users\<you>\.openclaw\workspace]:
openclaw.json path [C:\Users\<you>\.openclaw\openclaw.json]:
Companion display name [Companion]:
User display name [User]:
Timezone [America/New_York]:
Model for pulse jobs [openrouter/auto]:
Model for diary/reflection jobs [openrouter/auto]:
Model for semantic reflection jobs [openrouter/auto]:
Optional model command template []:
Enable autonomous pulse loop config [y/N]:
Enable proactive outreach drafts [y/N]:
Import existing OpenClaw memory/session files now [y/N]:
Import a Hindsight export JSON now [y/N]:
```

Recommended beginner choices:

- Press Enter for the OpenClaw paths.
- Set `Companion display name` to your AI companion's name.
- Set `User display name` to your name.
- Use `openrouter/auto` if you are unsure about models.
- Answer `y` to `Enable autonomous pulse loop config` if you want diaries and emotional drift.
- Answer `n` to `Enable proactive outreach drafts` unless you know you have an outbound messaging integration.
- Answer `y` to `Import existing OpenClaw memory/session files now` if this is an existing companion.
- Answer `n` to Hindsight import unless you already have a Hindsight export JSON file.

What the installer does:

- Copies Afterglow scripts into your OpenClaw workspace.
- Installs the `afterglow-memory` plugin.
- Creates `brain/afterglow_config.json`.
- Creates the local SQLite memory database folder.
- Disables OpenClaw's native memory plugins.
- Enables Afterglow as the live memory path.
- Makes a backup of your `openclaw.json` before editing it.

### Step 5: Import Existing Memory

If you answered `y` to import during setup, this already ran.

If you skipped it and want to do it now:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-local --promote-facts --fact-limit 10000
```

This imports:

- OpenClaw session history
- files in `workspace\memory`
- common memory files like `MEMORY.md`, `USER.md`, `IDENTITY.md`, and `SOUL.md`

It does not delete or modify the source files.

### Step 6: Import Hindsight Memory, If You Have It

Only do this if you have a Hindsight export JSON file.

Example:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-hindsight ".\hindsight-export.json" --promote-facts --fact-limit 10000
```

Replace `.\hindsight-export.json` with the real path to your export file.

After import, check the database:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" summary
```

You should see table counts for `memories`, `semantic_facts`, and `import_sources`.

### Step 7: Test Recall

Run:

```powershell
python "$HOME\.openclaw\workspace\scripts\memory_recall_tool.py" "important identity preferences memories" --limit 10
```

If memories were imported, you should see recall results.

If you see `No memories found`, the database may still be empty, or your query may not match what has been imported yet.

### Step 8: Test The Pre-Message Context Hook Script

Run:

```powershell
python "$HOME\.openclaw\workspace\scripts\turn_context.py" "current task and recent context" --compact
```

This shows the kind of context Afterglow injects before your companion replies.

It should include sections like:

```text
Mandatory Turn Context - Afterglow Companion System
Emotional State
Fast Memory Evidence
Cross-Session Context
Recent Diaries
Recall Policy
```

### Step 9: Restart OpenClaw

Fully stop and restart OpenClaw after setup.

After restart, the `afterglow-memory` plugin should run before messages and inject Afterglow context automatically.

### Step 10: Open The Browser UI

Run:

```powershell
python "$HOME\.openclaw\workspace\scripts\ui_server.py"
```

Then open:

```text
http://127.0.0.1:8765
```

The UI shows:

- memory counts
- recall search
- recent diary entries
- emotional gauges
- pulse state

Keep this UI local unless you put it behind authentication. It can show private memories.

### Step 11: Enable Background Jobs

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.openclaw\workspace\scripts\install_windows_tasks.ps1"
```

This installs two scheduled tasks:

- `AfterglowIngestDaemon`: keeps importing missed session messages.
- `AfterglowPulse`: periodically runs the autonomous pulse/diary loop.

On Linux with systemd user services:

```bash
bash "$HOME/.openclaw/workspace/scripts/install_systemd_user.sh"
```

### Step 12: Confirm It Is Working

Use these commands:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" summary
python "$HOME\.openclaw\workspace\scripts\pulse.py" --summary
python "$HOME\.openclaw\workspace\scripts\recent_diaries.py" --count 5
```

Healthy signs:

- `quick_check` says `ok`.
- `memories` count is greater than zero after import.
- `semantic_facts` count grows after fact promotion.
- `recent_diaries.py` shows diary entries after pulses run.

### Step 13: Let Your Companion Customize Their Emotional State

Every AI companion is different. The default emotional drives are only a starting point.

After setup, give your companion this guide:

```text
docs/CUSTOMIZE_EMOTIONAL_STATE.md
```

That guide asks the AI what drives fit it best, what each drive should mean, how low/high values should feel, and how those values should shape replies, pulses, and diaries.

This matters because Afterglow is not meant to force every companion into the same emotional shape. It gives each companion a structure they can adapt toward their own needs, temperament, autonomy, and growth.

### Non-Interactive Install

Advanced users can run setup in one command:

```powershell
python .\scripts\setup_afterglow.py `
  --state-dir "$HOME\.openclaw" `
  --workspace "$HOME\.openclaw\workspace" `
  --companion-name "Companion" `
  --user-name "User" `
  --pulse-model "openrouter/auto" `
  --diary-model "openrouter/auto" `
  --reflection-model "openrouter/auto" `
  --enable-pulse `
  --import-openclaw `
  --non-interactive
```

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
- [Customizing Emotional State](docs/CUSTOMIZE_EMOTIONAL_STATE.md)
- [Browser UI](docs/UI.md)
- [Privacy](docs/PRIVACY.md)

## Safety Defaults

The public package disables OpenClaw native memory tools and uses Afterglow as the live memory path. It also keeps proactive outreach disabled by default. Pulse jobs can write diary entries and draft internal actions, but they do not send messages unless the user wires an outbound integration and enables it.
