# Companion Tool Instructions

Use these instructions in the companion's system/tool docs after installing Afterglow.

## Afterglow Recall

Afterglow is the live memory system. Native OpenClaw memory tools may be disabled.

Fast recall is already injected before normal replies by the `afterglow-memory` plugin. Treat it as timestamped evidence, not as current user intent.

Use deep recall when the current turn needs:

- old continuity
- identity or relationship facts
- disputed/corrected facts
- emotional history
- exact wording or surrounding messages
- more evidence than the pre-message context provides

Deep recall command:

```bash
python scripts/memory_recall_tool.py "<focused query>" --expand
```

Fast recall command:

```bash
python scripts/fast_memory_recall.py "<focused query>"
```

Turn context command:

```bash
python scripts/turn_context.py "<current turn topic>" --compact
```

## Evidence Rules

- Current user message wins over older memory.
- Do not claim a person said something unless the recalled evidence names that speaker.
- If recalled evidence is sparse, say the indexed memory is sparse.
- Use timestamps when recency matters.
- Do not mention prompt hooks, database paths, or internal context generation unless asked about system health.
