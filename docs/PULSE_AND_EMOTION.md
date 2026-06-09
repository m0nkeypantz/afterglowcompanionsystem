# Pulse And Emotion

Afterglow tracks emotional state separately from memory.

## State Files

Structured state:

```text
brain/soul_state.json
```

Rendered prompt state:

```text
brain/context/emotional_state.md
```

Pulse state:

```text
brain/pulse_state.json
```

Pulse telemetry:

```text
brain/pulse_telemetry/
```

Diary entries:

```text
memory/afterglow_diary/
```

## Drives

Default drives:

- `satisfaction`
- `curiosity`
- `frustration`
- `social_battery`
- `loneliness`
- `boredom`
- `affection`
- `independence`
- `self_improvement`
- `self_coherence`
- `continuity`

`render_emotional_state.py` turns these into concise response guidance. The model should embody this guidance, not recite it.

## Pulse Loop

Run one pulse:

```powershell
python "$HOME\.openclaw\workspace\scripts\pulse.py" --force
```

Due-only pulse:

```powershell
python "$HOME\.openclaw\workspace\scripts\pulse.py" --once
```

Pulse flow:

1. Load `soul_state.json`.
2. Drift drives toward stable baselines.
3. Check recent cross-session activity, recall, and diaries.
4. Choose an internal action.
5. Build a pulse prompt.
6. Optionally call a configured model runner.
7. Write a diary entry.
8. Import the diary back into Afterglow.

## Model Choice

Configured in:

```text
brain/afterglow_config.json
```

Example:

```json
{
  "models": {
    "pulse": "openrouter/deepseek/deepseek-v4-flash",
    "diary": "openrouter/deepseek/deepseek-v4-flash",
    "reflection": "openrouter/auto",
    "recall": "local_sqlite_fts"
  }
}
```

The pulse script reads these values every run.

## Model Runner

By default, no model call is made. The pulse script writes prompt files and deterministic fallback diaries.

To call a model, configure:

```json
{
  "model_runner": {
    "command_template": "python scripts/my_model_runner.py --model {model} --prompt {prompt_path} --out {output_path}",
    "timeout_seconds": 120
  }
}
```

The runner should write the model response to `{output_path}` or print it to stdout.

## Outreach

Public default:

```json
{
  "pulse": {
    "outreach_enabled": false
  }
}
```

When disabled, pulse can only write internal diaries and pending drafts. It cannot send messages.

To support proactive texting, Discord, email, or other output, the user must add a separate outbound integration and explicitly enable it.
