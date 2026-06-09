# Architecture

Afterglow is split into six cooperating layers.

## 1. Canonical Memory Store

`scripts/afterglow.py` owns the local SQLite database at:

```text
<workspace>/brain/memory_index/afterglow.sqlite
```

Main tables:

- `memories`: normalized memories from OpenClaw sessions, markdown files, diary entries, Hindsight exports, and live hooks.
- `memories_fts`: SQLite FTS5 index for fast lexical recall.
- `semantic_facts`: promoted durable facts.
- `semantic_entities`: canonical subjects for semantic facts.
- `memory_recall_stats`: recall reinforcement/usage tracking.
- `import_sources`: source file fingerprints to avoid duplicate imports.

Imports are additive. Source files remain the audit trail.

## 2. Ingestion

Ingestion paths:

- `afterglow.py import-local`: imports local memory files and session files.
- `afterglow.py import-hindsight <file>`: imports a Hindsight JSON export.
- `afterglow.py ingest-message`: called by the plugin for live inbound/outbound messages.
- `afterglow_daemon.py`: fallback polling daemon for OpenClaw session files.

The fallback daemon exists because hooks can fail, OpenClaw can restart, and model/tool calls can time out. The daemon keeps memory moving even when the live hook misses an event.

## 3. Recall

Fast recall:

```text
scripts/fast_memory_recall.py
```

Deep/manual recall:

```text
scripts/memory_recall_tool.py
```

The plugin uses `turn_context.py`, which calls the local Afterglow recall path and writes `brain/current_response_context.json`.

For high-confidence answers, the assistant should treat recall as evidence. If the retrieved context is sparse or ambiguous, it should say so instead of inventing continuity.

## 4. Cross-Session Awareness

`cross_session_digest.py` scans recent OpenClaw session JSONL files and writes:

```text
<workspace>/brain/current_cross_session.json
```

`cross_session_recall.py` then searches that digest for current-turn relevance.

This does not merge sessions. It gives the current turn a compact awareness layer of recent activity elsewhere.

## 5. Turn Context Hook

`turn_context.py` is the pre-message injection script.

It assembles:

- current turn metadata
- rendered emotional state
- response-style adapter
- fast memory evidence
- cross-session context
- recent diary entries
- recall policy

The OpenClaw plugin calls it from `before_prompt_build` and prepends the result to the model prompt.

## 6. Emotion, Pulse, And Diary

`brain/soul_state.json` is the structured emotional state.

`render_emotional_state.py` renders it into:

```text
<workspace>/brain/context/emotional_state.md
```

`pulse.py` periodically:

- drifts emotional drives
- checks recent memory/session/diary context
- chooses an internal action
- writes a diary entry to `memory/afterglow_diary`
- imports that diary back into Afterglow

Model calls for pulse/diary writing are optional and configured in `brain/afterglow_config.json`.

If no model runner is configured, pulse jobs write deterministic fallback diaries and prompt files for review.
