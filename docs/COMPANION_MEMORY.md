# Companion Memory Blueprint

Afterglow keeps raw history, semantic facts, emotional state, diary writing, and pulse behavior separate. The companion-memory layer adds an inspectable overlay on top of the canonical SQLite database so recall feels more continuous in everyday conversation.

It is not a second memory database. It derives prompt-safe structures from `memories`, `semantic_facts`, `semantic_entities`, and recall statistics.

## Goals

- Preserve full chat history and source pointers.
- Promote durable facts without storing prompt wrappers or operational context as personal memories.
- Keep everyday continuity visible: recent casual facts, open loops, projects, people, preferences, emotional tone, and companion-side self-reflection.
- Prefer fast local recall for normal turns, while leaving deep recall available for high-confidence or disputed answers.
- Make recall inspectable with traces, evals, audits, and dashboard JSON.

## Derived Layers

### Observations

`scripts/afterglow_companion_memory.py rebuild` scans recent memories and writes:

```text
brain/memory_index/companion_observations.json
```

It also creates the `companion_observations` SQLite table.

Observation types include:

- `recent_context`
- `emotional_continuity`
- `project_thread`
- `unresolved_loop`
- `preference`
- `relationship`
- `companion_self`
- `small_stuff`

Each observation keeps a source memory ID, timestamp, lane, speaker, confidence, and a short evidence quote.

### Episodes

Recent observations are grouped into daily/topic episodes:

```text
brain/memory_index/companion_episodes.json
```

Episodes are useful when the companion needs to understand what a day or thread was about without rereading every raw message.

### Reflection

The overlay writes:

```text
brain/memory_index/companion_reflection.json
brain/context/afterglow_companion_reflection.md
```

This reflection is intentionally compact. It highlights:

- important active threads
- unresolved loops
- emotional continuity
- companion self-context
- recent small-stuff context

`turn_context.py` and `fast_memory_recall.py` include this overlay when available.

### Relationship Graph

`scripts/afterglow_relationship_refresh.py` derives `relationship_edges` from active semantic facts and recent co-mentions.

Semantic facts remain authoritative. The relationship graph is a fast map for dashboards, debugging, and future recall tools.

### Recall Tracing

Fast recall and turn-context recall append trace entries to:

```text
logs/afterglow_recall_trace.jsonl
```

Each trace records the query, selected memory IDs, scores, reasons, lane, and latency.

### Prompt-Leak Audit

`scripts/afterglow_prompt_leak_audit.py` scans `memories` and `semantic_facts` for prompt wrappers, tool primers, operational metadata, and credential chatter.

The audit is read-only. It writes:

```text
brain/afterglow_prompt_leak_audit.json
```

## Maintenance Commands

Recommended after imports and periodically:

```powershell
python scripts/afterglow.py promote-facts --limit 3000
python scripts/afterglow_companion_memory.py rebuild --json
python scripts/afterglow_relationship_refresh.py --json
python scripts/afterglow_prompt_leak_audit.py --json
python scripts/afterglow_eval_suite.py --json
python scripts/afterglow_recall_dashboard.py --json
python scripts/rotate_afterglow_logs.py
```

Suggested cadence:

- every message: plugin ingestion and `turn_context.py`
- every 2-10 minutes: `afterglow_daemon.py` fallback ingest, if used
- hourly: companion overlay rebuild and relationship refresh
- daily: prompt leak audit, eval suite, dashboard JSON, log rotation

## Prompt Guidance

When injecting memory into a companion prompt, keep the policy simple:

- Treat retrieved memories as timestamped evidence.
- Preserve speaker/source labels and dates when making claims.
- Current user message wins over old memory if they conflict.
- If cross-session context happened after this thread's last message, consider it before answering continuity questions.
- For exact wording, disputed facts, or older emotional history, run deep recall before making strong claims.
- If evidence is sparse, say the indexed memory is sparse.

## Public Package Boundary

The public package must stay blank-state:

- no private memories
- no private user or companion data
- no credentials
- no deployment paths
- no phone, wearable, bridge, or chat-lane assumptions beyond generic source labels

Use `companion_name`, `user_name`, and `companion_memory` settings in `brain/afterglow_config.json` to adapt the system locally.
