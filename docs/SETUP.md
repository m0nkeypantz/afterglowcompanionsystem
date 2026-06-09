# Setup

## Requirements

- Python 3.10+
- OpenClaw installed
- SQLite with FTS5 support, included in normal Python builds
- Optional: OpenRouter/OpenAI/etc. credentials configured in OpenClaw if you want model-written pulse diaries

No Node build step is required for the Python tools or browser UI.

## Interactive Install

Run from this repository:

```powershell
python .\scripts\setup_afterglow.py
```

The installer copies scripts into:

```text
<openclaw workspace>/scripts
```

It copies the plugin into both known plugin locations:

```text
<openclaw state>/plugins/afterglow-memory
<openclaw workspace>/plugins/afterglow-memory
```

It also patches `openclaw.json` to:

- enable `afterglow-memory`
- disable `memory-core`
- disable `memory-wiki`
- set `plugins.slots.memory` to `none`
- deny native `memory_*`, `wiki_*`, and `brain__*` tools
- disable internal `session-memory`

A backup is written next to `openclaw.json`.

## Non-Interactive Install

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

## Verify

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" summary
python "$HOME\.openclaw\workspace\scripts\turn_context.py" "current memory setup" --compact
python "$HOME\.openclaw\workspace\scripts\pulse.py" --force
python "$HOME\.openclaw\workspace\scripts\ui_server.py"
```

Open:

```text
http://127.0.0.1:8765
```

## Model Runner

The pulse engine can call a model only if `brain/afterglow_config.json` has a command template.

Template fields:

- `{model}`
- `{session_key}`
- `{prompt_path}`
- `{output_path}`

Example placeholder:

```json
{
  "model_runner": {
    "command_template": "python scripts/my_model_runner.py --model {model} --prompt {prompt_path} --out {output_path}",
    "timeout_seconds": 120
  }
}
```

If `command_template` is empty, pulse writes the prompt file and a fallback diary locally. That is intentional and safe for first install.
