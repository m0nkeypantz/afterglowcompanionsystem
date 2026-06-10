# Changelog

## 2026-06-10 - Companion Memory Overlay And Recall Observability

- Added a companion-memory overlay that derives prompt-safe observations, episodes, reflection markdown, and small-stuff continuity from the canonical SQLite memory store.
- Added recall trace logging for fast recall and turn-context injection so query latency and selected memory IDs can be audited.
- Added a relationship graph refresh command that derives `relationship_edges` from active semantic facts and recent co-mentions.
- Added a read-only prompt-leak audit for system wrappers, tool primers, operational context, and credential chatter.
- Added a recall dashboard JSON generator and lightweight eval suite for ongoing memory health checks.
- Added standalone log rotation for Afterglow audit/trace logs.
- Updated setup/config/docs so new installs can rebuild and inspect companion-memory layers without private deployment data.

## 2026-06-09 - Hindsight++ Semantic Fact Promotion

- Added stricter semantic fact promotion guardrails so prompt wrappers, bridge/system context, tool primers, API-key chatter, and operational diagnostics are not promoted as companion memories.
- Added source/evidence metadata to promoted facts, including memory class, durability, speaker, lane, evidence quote, and retrieval cues where available.
- Added exact active-fact duplicate detection so repeated imports do not refresh old facts and make them look newly learned.
- Added `logs/semantic_fact_promotion_audit.jsonl` for promotion tracing. Each candidate is recorded as promoted, skipped, or rejected with the reason.
- Updated live `ingest-message` and batch promotion to use the same promotion path for more predictable memory behavior across hooks, imports, and background jobs.
