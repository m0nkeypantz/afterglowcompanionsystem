# Privacy

This public package intentionally contains no private companion data.

Do not commit:

- `brain/memory_index/afterglow.sqlite`
- `brain/soul_state.json` from a real companion unless intentionally public
- `memory/afterglow_diary`
- `logs`
- OpenClaw credentials
- Hindsight exports
- `openclaw.json` if it contains tokens or channel credentials

## Sanitization

This repository uses generic names:

- `turn_context.py` instead of a person-specific context script
- `Companion` and `User` defaults
- generic `<user_message>` / `<turn_message>` transport tags
- generic pulse language

The plugin has a small outbound redaction guard for:

- API keys
- labeled secrets
- phone numbers

That guard is not a substitute for proper private/public channel policy. It is a last-mile safety layer only.

## Database Sharing

An Afterglow database is a companion identity artifact. Sharing it shares memory.

For blank-state installs, share the code only. Do not include:

```text
brain/
memory/
logs/
```

## Public UI Warning

The UI can display diaries and memories. Keep it on `127.0.0.1` unless it is behind an authenticated reverse proxy.
