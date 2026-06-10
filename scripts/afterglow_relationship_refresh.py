#!/usr/bin/env python3
"""Build a lightweight relationship graph from Afterglow semantic facts.

The graph is intentionally derived, not authoritative. Semantic facts remain
the source of truth; this table gives dashboards and recall tools a fast way
to inspect active relationship edges, co-mentions, and stale/conflicting links.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402
from afterglow_config import load_config  # noqa: E402


CONFIG = load_config()
COMPANION_CFG = CONFIG.get("companion_memory", {}) if isinstance(CONFIG.get("companion_memory"), dict) else {}
REPORT_PATH = afterglow.BRAIN / "relationship_graph_last_refresh.json"

DEFAULT_RELATIONSHIP_PREDICATES = {
    "parent_of",
    "child_of",
    "sibling_of",
    "partner_of",
    "friend_of",
    "works_with",
    "knows",
    "cares_about",
    "trusts",
    "likes",
    "dislikes",
    "prefers",
    "belongs_to",
    "owns",
    "uses",
    "working_on",
    "goal",
    "promise",
    "boundary",
    "identity",
    "role",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_json(raw: Any, default: Any) -> Any:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if value is not None else default
    except Exception:
        return default


def stable_id(*parts: Any, length: int = 24) -> str:
    return afterglow.stable_id(*parts, length=length)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS relationship_edges (
            id TEXT PRIMARY KEY,
            subject_entity_id TEXT,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_entity_id TEXT,
            object TEXT NOT NULL,
            source_memory_id TEXT,
            source_fact_id TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'active',
            valid_from TEXT,
            valid_to TEXT,
            last_seen_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_relationship_edges_subject ON relationship_edges(subject);
        CREATE INDEX IF NOT EXISTS idx_relationship_edges_object ON relationship_edges(object);
        CREATE INDEX IF NOT EXISTS idx_relationship_edges_predicate ON relationship_edges(predicate);
        CREATE INDEX IF NOT EXISTS idx_relationship_edges_status ON relationship_edges(status);
        """
    )


def entity_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT id, canonical_name, entity_type, aliases_json
        FROM semantic_entities
        ORDER BY canonical_name COLLATE NOCASE
        """
    ).fetchall()


def entity_alias_index(con: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    lookup: dict[str, dict[str, Any]] = {}
    aliases_by_id: dict[str, list[str]] = {}
    for row in entity_rows(con):
        aliases = [str(row["canonical_name"] or "").strip()]
        aliases.extend(str(x).strip() for x in parse_json(row["aliases_json"], []) if str(x).strip())
        aliases = sorted({a for a in aliases if a}, key=len, reverse=True)
        aliases_by_id[row["id"]] = aliases
        for alias in aliases:
            lookup[alias.lower()] = {
                "id": row["id"],
                "name": row["canonical_name"],
                "type": row["entity_type"],
            }
    return lookup, aliases_by_id


def resolve_entity(lookup: dict[str, dict[str, Any]], text: Any) -> dict[str, Any]:
    key = str(text or "").strip().lower()
    if not key:
        return {"id": None, "name": ""}
    if key in lookup:
        return lookup[key]
    return {"id": None, "name": str(text or "").strip()}


def relationship_predicates() -> set[str]:
    configured = COMPANION_CFG.get("custom_relationship_predicates") or []
    return {p.lower().strip() for p in DEFAULT_RELATIONSHIP_PREDICATES | set(map(str, configured)) if p}


def upsert_edge(con: sqlite3.Connection, edge: dict[str, Any]) -> None:
    con.execute(
        """
        INSERT INTO relationship_edges(
            id, subject_entity_id, subject, predicate, object_entity_id, object,
            source_memory_id, source_fact_id, confidence, status, valid_from,
            valid_to, last_seen_at, created_at, updated_at, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            confidence=max(relationship_edges.confidence, excluded.confidence),
            status=excluded.status,
            valid_from=COALESCE(excluded.valid_from, relationship_edges.valid_from),
            valid_to=excluded.valid_to,
            last_seen_at=excluded.last_seen_at,
            updated_at=excluded.updated_at,
            metadata_json=excluded.metadata_json
        """,
        (
            edge["id"],
            edge.get("subject_entity_id"),
            edge["subject"],
            edge["predicate"],
            edge.get("object_entity_id"),
            edge["object"],
            edge.get("source_memory_id"),
            edge.get("source_fact_id"),
            float(edge.get("confidence") or 0.5),
            edge.get("status") or "active",
            edge.get("valid_from"),
            edge.get("valid_to"),
            edge.get("last_seen_at"),
            edge.get("created_at") or now_iso(),
            edge.get("updated_at") or now_iso(),
            json.dumps(edge.get("metadata") or {}, ensure_ascii=False),
        ),
    )


def refresh_fact_edges(con: sqlite3.Connection, lookup: dict[str, dict[str, Any]]) -> int:
    now = now_iso()
    predicates = relationship_predicates()
    rows = con.execute(
        """
        SELECT id, subject_entity_id, subject, predicate, object, object_entity_id,
               memory_id, confidence, status, valid_from, valid_to, event_time,
               summary, source_ids_json, tags_json
        FROM semantic_facts
        WHERE status='active'
        ORDER BY updated_at DESC
        """
    ).fetchall()
    count = 0
    for row in rows:
        predicate = str(row["predicate"] or "").strip().lower()
        if predicate not in predicates:
            continue
        subject = resolve_entity(lookup, row["subject"])
        obj = resolve_entity(lookup, row["object"])
        edge_id = stable_id("fact", subject.get("id") or subject["name"], predicate, obj.get("id") or obj["name"], row["id"])
        upsert_edge(
            con,
            {
                "id": edge_id,
                "subject_entity_id": row["subject_entity_id"] or subject.get("id"),
                "subject": subject.get("name") or str(row["subject"]),
                "predicate": predicate,
                "object_entity_id": row["object_entity_id"] or obj.get("id"),
                "object": obj.get("name") or str(row["object"]),
                "source_memory_id": row["memory_id"],
                "source_fact_id": row["id"],
                "confidence": row["confidence"],
                "status": row["status"],
                "valid_from": row["valid_from"] or row["event_time"],
                "valid_to": row["valid_to"],
                "last_seen_at": row["event_time"] or now,
                "created_at": now,
                "updated_at": now,
                "metadata": {
                    "source": "semantic_fact",
                    "summary": row["summary"],
                    "source_ids": parse_json(row["source_ids_json"], []),
                    "tags": parse_json(row["tags_json"], []),
                },
            },
        )
        count += 1
    return count


def mentioned_entities(text: str, aliases_by_id: dict[str, list[str]], names_by_id: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    haystack = f" {text.lower()} "
    for entity_id, aliases in aliases_by_id.items():
        for alias in aliases:
            cleaned = alias.lower().strip()
            if len(cleaned) < 3:
                continue
            if re.search(rf"(?<![a-z0-9_]){re.escape(cleaned)}(?![a-z0-9_])", haystack, flags=re.I):
                found.append((entity_id, names_by_id.get(entity_id) or aliases[0]))
                break
    return found


def refresh_comention_edges(con: sqlite3.Connection, aliases_by_id: dict[str, list[str]], days: int, limit: int) -> int:
    now = now_iso()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat().replace("+00:00", "Z")
    names_by_id = {eid: aliases[0] for eid, aliases in aliases_by_id.items() if aliases}
    core = {str(x).lower() for x in COMPANION_CFG.get("relationship_core_entities") or []}
    rows = con.execute(
        """
        SELECT id, timestamp_iso, summary, text, source_kind, source_path
        FROM memories
        WHERE timestamp_iso >= ?
        ORDER BY timestamp_iso DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()
    count = 0
    for row in rows:
        text = f"{row['summary'] or ''}\n{row['text'] or ''}"
        mentions = mentioned_entities(text, aliases_by_id, names_by_id)
        if len(mentions) < 2:
            continue
        for i, left in enumerate(mentions[:8]):
            for right in mentions[i + 1 : 8]:
                if core and left[1].lower() not in core and right[1].lower() not in core:
                    continue
                edge_id = stable_id("comention", left[0], right[0], row["id"])
                upsert_edge(
                    con,
                    {
                        "id": edge_id,
                        "subject_entity_id": left[0],
                        "subject": left[1],
                        "predicate": "co_mentioned_with",
                        "object_entity_id": right[0],
                        "object": right[1],
                        "source_memory_id": row["id"],
                        "confidence": 0.45,
                        "status": "active",
                        "last_seen_at": row["timestamp_iso"] or now,
                        "created_at": now,
                        "updated_at": now,
                        "metadata": {
                            "source": "recent_memory_co_mention",
                            "source_kind": row["source_kind"],
                            "source_path": row["source_path"],
                            "summary": afterglow.one_line(row["summary"] or row["text"], 260),
                        },
                    },
                )
                count += 1
    return count


def refresh(days: int | None = None, limit: int | None = None) -> dict[str, Any]:
    days = int(days or COMPANION_CFG.get("relationship_edge_days") or 30)
    limit = int(limit or 2500)
    with afterglow.connect() as con:
        ensure_schema(con)
        lookup, aliases_by_id = entity_alias_index(con)
        con.execute("UPDATE relationship_edges SET status='stale', updated_at=? WHERE predicate != 'co_mentioned_with'", (now_iso(),))
        fact_edges = refresh_fact_edges(con, lookup)
        comention_edges = refresh_comention_edges(con, aliases_by_id, days=days, limit=limit)
        counts = {
            row["predicate"]: row["n"]
            for row in con.execute("SELECT predicate, COUNT(*) AS n FROM relationship_edges WHERE status='active' GROUP BY predicate")
        }
        active = con.execute("SELECT COUNT(*) FROM relationship_edges WHERE status='active'").fetchone()[0]
        con.commit()
    payload = {
        "generated_at": now_iso(),
        "db": str(afterglow.DB_PATH),
        "relationship_edges_active": active,
        "fact_edges_refreshed": fact_edges,
        "comention_edges_refreshed": comention_edges,
        "predicate_counts": counts,
        "days": days,
        "limit": limit,
    }
    afterglow.save_json(REPORT_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Afterglow relationship graph")
    parser.add_argument("--days", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = refresh(days=args.days, limit=args.limit)
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"relationship edges active: {payload['relationship_edges_active']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
