# Changelog

## 2026-06-09 - Hindsight++ Semantic Fact Promotion

- Added stricter semantic fact promotion guardrails so prompt wrappers, bridge/system context, tool primers, API-key chatter, and operational diagnostics are not promoted as companion memories.
- Added source/evidence metadata to promoted facts, including memory class, durability, speaker, lane, evidence quote, and retrieval cues where available.
- Added exact active-fact duplicate detection so repeated imports do not refresh old facts and make them look newly learned.
- Added `logs/semantic_fact_promotion_audit.jsonl` for promotion tracing. Each candidate is recorded as promoted, skipped, or rejected with the reason.
- Updated live `ingest-message` and batch promotion to use the same promotion path for more predictable memory behavior across hooks, imports, and background jobs.
