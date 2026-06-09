# OpenClaw Integration

The plugin lives at:

```text
plugins/afterglow-memory
```

After install, OpenClaw should have:

```json
{
  "plugins": {
    "slots": {
      "memory": "none"
    },
    "entries": {
      "memory-core": { "enabled": false },
      "memory-wiki": { "enabled": false },
      "afterglow-memory": { "enabled": true }
    }
  }
}
```

## Hooks

### `before_prompt_build`

The plugin calls:

```text
python scripts/turn_context.py "<query>" --turn-json-base64 "<event/context>" --compact --fast
```

The returned text is prepended to the model prompt.

This is the important hook. It makes recall happen before the model answers instead of racing in the background.

### `message_received`

The plugin calls:

```text
python scripts/afterglow.py ingest-message "<message>" --role user --source openclaw.message_received
```

This writes live inbound messages to the Afterglow database.

### `message_sending`

The plugin writes outbound assistant messages back to Afterglow and appends a lightweight delivery log:

```text
brain/afterglow_delivery_writeback.jsonl
```

It also has a generic redaction guard for credentials and phone numbers.

## Prompt Supplement

The plugin also registers a memory prompt supplement as a fallback. This can inject:

- `brain/afterglow_prompt_recall.md`
- `brain/current_response_context.json`
- `brain/context/emotional_state.md`

The synchronous `before_prompt_build` context is still the primary path.

## Fallback Daemon

`afterglow_daemon.py` polls OpenClaw session JSONL files and imports anything missed by hooks.

Run manually:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow_daemon.py" --interval 5
```

Or install scheduler helpers from `scripts/install_windows_tasks.ps1` or `scripts/install_systemd_user.sh`.

## Avoiding Tool Loops

The installer disables native OpenClaw memory tools:

```json
{
  "tools": {
    "deny": ["memory_*", "wiki_*", "brain__*"]
  }
}
```

This prevents the model from repeatedly calling missing or stale native memory tools while Afterglow owns recall.
