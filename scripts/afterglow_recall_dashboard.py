#!/usr/bin/env python3
"""Generate a JSON dashboard for Afterglow recall quality and freshness."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402

try:
    from afterglow_companion_memory import recent_recall_traces, rebuild_reflection
except Exception:  # pragma: no cover - optional overlay should not break dashboard
    recent_recall_traces = None  # type: ignore[assignment]
    rebuild_reflection = None  # type: ignore[assignment]


REPORT_PATH = afterglow.BRAIN / "afterglow_recall_dashboard.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(row)


def scalar(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = con.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def rows_as_dicts(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in con.execute(sql, params).fetchall()]


def build(refresh: bool = False) -> dict[str, Any]:
    if refresh and rebuild_reflection:
        try:
            rebuild_reflection()
        except Exception:
            pass
    summary = afterglow.summary()
    with afterglow.connect() as con:
        con.row_factory = sqlite3.Row
        semantic_status = rows_as_dicts(
            con,
            "SELECT status, COUNT(*) AS count FROM semantic_facts GROUP BY status ORDER BY count DESC",
        )
        type_counts = rows_as_dicts(
            con,
            "SELECT COALESCE(type, 'unknown') AS type, COUNT(*) AS count FROM memories GROUP BY type ORDER BY count DESC LIMIT 20",
        )
        source_counts = rows_as_dicts(
            con,
            "SELECT COALESCE(source_kind, 'unknown') AS source_kind, COUNT(*) AS count FROM memories GROUP BY source_kind ORDER BY count DESC LIMIT 20",
        )
        recent = rows_as_dicts(
            con,
            """
            SELECT id, type, timestamp_iso, source_kind, summary
            FROM memories
            ORDER BY timestamp_iso DESC
            LIMIT 12
            """,
        )
        top_recalled = rows_as_dicts(
            con,
            """
            SELECT m.id, m.type, m.timestamp_iso, m.source_kind, m.summary,
                   s.recall_count, s.last_score, s.reinforcement, s.last_recalled_at
            FROM memory_recall_stats s
            JOIN memories m ON m.id=s.memory_id
            ORDER BY s.recall_count DESC, s.last_recalled_at DESC
            LIMIT 12
            """,
        )
        companion_counts: dict[str, int] = {}
        for table in ("companion_observations", "companion_episodes", "companion_reflections", "relationship_edges"):
            companion_counts[table] = int(scalar(con, f"SELECT COUNT(*) FROM {table}") or 0) if table_exists(con, table) else 0
        relationship_counts = (
            rows_as_dicts(con, "SELECT predicate, status, COUNT(*) AS count FROM relationship_edges GROUP BY predicate, status ORDER BY count DESC LIMIT 25")
            if table_exists(con, "relationship_edges")
            else []
        )
        duplicate_entities = rows_as_dicts(
            con,
            """
            SELECT lower(canonical_name) AS name_key, COUNT(*) AS count,
                   group_concat(canonical_name, ', ') AS names
            FROM semantic_entities
            GROUP BY lower(canonical_name)
            HAVING COUNT(*) > 1
            ORDER BY count DESC, name_key
            LIMIT 25
            """,
        )
    traces = recent_recall_traces(limit=12) if recent_recall_traces else {"entries": []}
    payload = {
        "generated_at": afterglow.now_iso(),
        "summary": summary,
        "semantic_fact_status": semantic_status,
        "memory_type_counts": type_counts,
        "source_kind_counts": source_counts,
        "recent_memories": recent,
        "top_recalled": top_recalled,
        "companion_layer_counts": companion_counts,
        "relationship_counts": relationship_counts,
        "duplicate_entity_candidates": duplicate_entities,
        "prompt_leak_audit": load_json(afterglow.BRAIN / "afterglow_prompt_leak_audit.json", {}),
        "relationship_refresh": load_json(afterglow.BRAIN / "relationship_graph_last_refresh.json", {}),
        "eval_last": load_json(afterglow.BRAIN / "afterglow_eval_last.json", {}),
        "recall_traces": traces.get("entries", []),
    }
    afterglow.save_json(REPORT_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Afterglow recall dashboard JSON")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    payload = build(refresh=args.refresh)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        tables = payload["summary"].get("tables", {})
        print(f"memories={tables.get('memories', 0)} semantic_facts={tables.get('semantic_facts', 0)} observations={payload['companion_layer_counts'].get('companion_observations', 0)}")
        print(f"dashboard: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
