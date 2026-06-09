# Migration

Afterglow migration is additive. It imports from existing stores into a new local SQLite database and leaves original files untouched.

## Import Existing OpenClaw Memory

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-local --promote-facts --fact-limit 10000
```

This scans:

- `workspace/memory`
- `workspace/MEMORY.md`
- `workspace/pending_brain_writes.md`
- `workspace/USER.md`
- `workspace/IDENTITY.md`
- `workspace/SOUL.md`
- OpenClaw session JSONL files

To limit session import:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-local --max-session-files 200 --promote-facts
```

## Import Hindsight Export

1. Export Hindsight to JSON.
2. Place the export somewhere local.
3. Run:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" import-hindsight ".\hindsight-export.json" --promote-facts --fact-limit 10000
```

Verify:

```powershell
python "$HOME\.openclaw\workspace\scripts\afterglow.py" summary
python "$HOME\.openclaw\workspace\scripts\memory_recall_tool.py" "important identity preferences relationship" --limit 10
```

## Disable Native OpenClaw Memory

The installer does this automatically. The intended result is:

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
  },
  "tools": {
    "deny": ["memory_*", "wiki_*", "brain__*"]
  }
}
```

This reduces loops caused by models trying to call old memory tools or missing memory paths.

## No Cross-Companion Import

Do not copy another companion's `afterglow.sqlite` into a new companion unless you intentionally want those memories to become part of the new identity.

For blank-state installs, run setup without `--import-openclaw` and without `--hindsight-export`.

## Backup Recommendation

Before migration:

```powershell
Compress-Archive "$HOME\.openclaw" "$HOME\openclaw-before-afterglow.zip"
```

After migration, keep:

- Hindsight export JSON
- original `.openclaw` backup
- `brain/memory_index/afterglow.sqlite`
