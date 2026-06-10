#!/usr/bin/env python3
"""Companion-shaped memory overlays for Afterglow.

This module derives lightweight, inspectable layers from the canonical
Afterglow SQLite store. It does not replace raw chat history or semantic facts.
It adds companion-oriented observations, episodes, reflections, and trace
logging so recall can stay fast while still feeling continuous.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
import sys

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402
from afterglow_config import load_config  # noqa: E402


CONFIG = load_config()
COMPANION_CFG = CONFIG.get("companion_memory", {}) if isinstance(CONFIG.get("companion_memory"), dict) else {}
USER_NAME = str(CONFIG.get("user_name") or "User")
COMPANION_NAME = str(CONFIG.get("companion_name") or "Companion")

WORKSPACE = afterglow.WORKSPACE
BRAIN = afterglow.BRAIN
DB_PATH = afterglow.DB_PATH
INDEX_DIR = BRAIN / "memory_index"
CONTEXT_DIR = BRAIN / "context"
OBSERVATIONS_PATH = INDEX_DIR / "companion_observations.json"
EPISODES_PATH = INDEX_DIR / "companion_episodes.json"
REFLECTION_PATH = INDEX_DIR / "companion_reflection.json"
REFLECTION_MD_PATH = CONTEXT_DIR / "afterglow_companion_reflection.md"
TRACE_LOG_PATH = WORKSPACE / "logs" / "afterglow_recall_trace.jsonl"

PROMPT_LEAK_PATTERNS = [
    r"<bridge_system_context",
    r"</bridge_system_context>",
    r"<user_message>",
    r"Text-Thinking-Level:",
    r"OpenClaw-Thinking:",
    r"Mandatory Turn Context",
    r"generated_by:\s*afterglow-memory",
    r"This is bridge/system context",
    r"not\s+(?:the\s+)?user speaking",
    r"Only the text inside",
    r"tool usage:",
    r"API key",
]
PROMPT_LEAK_RE = re.compile("|".join(PROMPT_LEAK_PATTERNS), re.I)

EMOTIONAL_WORDS = {
    "sad", "happy", "angry", "mad", "upset", "anxious", "worried", "scared",
    "lonely", "drained", "hopeful", "excited", "proud", "hurt", "love",
    "affection", "frustrated", "comfort", "reassurance", "relief", "joy",
}
RECENT_WORDS = {
    "today", "yesterday", "earlier", "recent", "currently", "now", "just",
    "tonight", "morning", "afternoon", "evening", "last night", "this week",
}
PROJECT_WORDS = {
    "project", "projects", "build", "building", "app", "bridge", "memory",
    "dashboard", "openclaw", "workflow", "feature", "system", "tool",
}
UNRESOLVED_WORDS = {
    "todo", "next", "later", "need", "needs", "pending", "follow", "followup",
    "promise", "promised", "remind", "remember to", "fix", "finish",
}
PREFERENCE_WORDS = {
    "prefer", "preference", "like", "likes", "liked", "dislike", "favorite",
    "avoid", "enjoy", "routine", "habit", "boundary", "style",
}
SELF_WORDS = {
    "you", "your", "yourself", "dream", "diary", "emotion", "mood", "goal",
    "goals", "want", "wants", "autonomy", "pulse", "reflection",
}
RELATIONSHIP_WORDS = {
    "relationship", "friend", "family", "partner", "care", "trust", "bond",
    "together", "between", "we", "us", "our",
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def stable_id(*parts: Any, length: int = 24) -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:length]


def one_line(text: Any, limit: int = 360) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 1)].rstrip() + "..."


def parse_json(raw: Any, default: Any) -> Any:
    try:
        if raw is None:
            return default
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if value is not None else default
    except Exception:
        return default


def parse_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def ensure_companion_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS companion_observations (
            id TEXT PRIMARY KEY,
            observation_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            companion_axis TEXT NOT NULL DEFAULT 'shared',
            speaker TEXT,
            lane TEXT,
            timestamp TEXT,
            timestamp_iso TEXT,
            source_memory_id TEXT,
            source_path TEXT,
            source_section TEXT,
            evidence_text TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            importance REAL NOT NULL DEFAULT 5,
            tags_json TEXT NOT NULL DEFAULT '[]',
            valid_from TEXT,
            valid_to TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_memory_id) REFERENCES memories(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_companion_observations_type ON companion_observations(observation_type);
        CREATE INDEX IF NOT EXISTS idx_companion_observations_subject ON companion_observations(subject);
        CREATE INDEX IF NOT EXISTS idx_companion_observations_axis ON companion_observations(companion_axis);
        CREATE INDEX IF NOT EXISTS idx_companion_observations_time ON companion_observations(timestamp_iso);
        CREATE TABLE IF NOT EXISTS companion_episodes (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            start_ts TEXT,
            end_ts TEXT,
            lane TEXT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            participants_json TEXT NOT NULL DEFAULT '[]',
            topics_json TEXT NOT NULL DEFAULT '[]',
            emotion_tags_json TEXT NOT NULL DEFAULT '[]',
            source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
            unresolved_json TEXT NOT NULL DEFAULT '[]',
            companion_axis TEXT NOT NULL DEFAULT 'shared',
            importance REAL NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_companion_episodes_date ON companion_episodes(date);
        CREATE INDEX IF NOT EXISTS idx_companion_episodes_time ON companion_episodes(start_ts);
        CREATE TABLE IF NOT EXISTS companion_reflections (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            focus_json TEXT NOT NULL DEFAULT '{}',
            evidence_ids_json TEXT NOT NULL DEFAULT '[]',
            generated_at TEXT NOT NULL,
            expires_at TEXT,
            confidence REAL NOT NULL DEFAULT 0.6,
            reflection_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_companion_reflections_scope ON companion_reflections(scope);
        """
    )


def connect() -> sqlite3.Connection:
    con = afterglow.connect()
    con.row_factory = sqlite3.Row
    ensure_companion_schema(con)
    return con


def clean_memory_text(text: Any) -> str:
    s = str(text or "")
    s = re.sub(r"<bridge_system_context[\s\S]*?</bridge_system_context>", " ", s, flags=re.I)
    s = re.sub(r"<(?:user_message|human_message|companion_user_message|turn_message)>\s*([\s\S]*?)\s*</(?:user_message|human_message|companion_user_message|turn_message)>", r"\1", s, flags=re.I)
    kept: list[str] = []
    for line in s.splitlines():
        low = line.strip().lower()
        if not low:
            kept.append("")
            continue
        if low.startswith("[text-thinking-level:") or low.startswith("[openclaw-thinking:"):
            continue
        if "bridge/system context" in low or "mandatory turn context" in low:
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def is_prompt_leak(text: Any) -> bool:
    return bool(PROMPT_LEAK_RE.search(str(text or "")))


def words(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text.lower()))


def source_lane_for_memory(row: sqlite3.Row | dict[str, Any]) -> str:
    entry = parse_json(row["entry_json"] if isinstance(row, sqlite3.Row) else row.get("entry_json"), {})
    source = entry.get("source", {}) if isinstance(entry, dict) else {}
    blob = " ".join(
        str(x or "")
        for x in (
            row["source_kind"] if isinstance(row, sqlite3.Row) else row.get("source_kind"),
            row["source_path"] if isinstance(row, sqlite3.Row) else row.get("source_path"),
            row["source_section"] if isinstance(row, sqlite3.Row) else row.get("source_section"),
            source.get("source"),
            source.get("channel"),
            source.get("adapter"),
        )
    ).lower()
    aliases = {
        "discord": ("discord", "guild", "channel", "dm"),
        "phone_text": ("phone_text", "phone text", "text lane", "message view", "sms"),
        "phone_voice": ("phone_voice", "voice call", "voice-live", "call lane"),
        "watch_voice": ("watch", "wear os"),
        "body": ("body", "device", "embedded"),
        "autonomy": ("pulse", "autonomy", "heartbeat", "dream", "diary"),
        "hindsight": ("hindsight",),
    }
    for lane, keys in aliases.items():
        if any(key in blob for key in keys):
            return lane
    return "openclaw"


def speaker_for_memory(row: sqlite3.Row, text: str) -> str:
    entry = parse_json(row["entry_json"], {})
    source = entry.get("source", {}) if isinstance(entry, dict) else {}
    for key in ("speaker", "author", "user", "name"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    role = str(source.get("role") or "").lower()
    if role == "assistant":
        return COMPANION_NAME
    if role == "user":
        return USER_NAME
    prefix = re.match(r"^\s*([A-Z][\w .'-]{1,40})\s*:", text)
    if prefix:
        return prefix.group(1).strip()
    return ""


def classify_memory(row: sqlite3.Row) -> dict[str, Any] | None:
    raw = f"{row['summary'] or ''}\n{row['text'] or ''}"
    if is_prompt_leak(raw):
        return None
    text = clean_memory_text(raw)
    if len(text) < 8:
        return None
    low_words = words(text)
    speaker = speaker_for_memory(row, text)
    speaker_low = speaker.lower()
    user_low = USER_NAME.lower()
    companion_low = COMPANION_NAME.lower()
    generic_companion_names = {"companion", "assistant", "ai", "bot"}
    companion_name_mentioned = companion_low not in generic_companion_names and companion_low in low_words

    observation_type = "casual_context"
    tags: list[str] = []
    if low_words & PREFERENCE_WORDS:
        observation_type = "preference"
        tags.append("preference")
    if low_words & UNRESOLVED_WORDS:
        observation_type = "open_thread"
        tags.append("unresolved")
    if low_words & PROJECT_WORDS:
        observation_type = "project_state" if observation_type == "casual_context" else observation_type
        tags.append("project")
    if low_words & EMOTIONAL_WORDS:
        observation_type = "emotional_context" if observation_type == "casual_context" else observation_type
        tags.append("emotion")
    if low_words & RECENT_WORDS:
        tags.append("recent")
    if low_words & RELATIONSHIP_WORDS:
        tags.append("relationship")

    if speaker_low == companion_low or companion_name_mentioned or (low_words & SELF_WORDS and "you" in low_words):
        axis = "companion_self"
        subject = COMPANION_NAME
    elif speaker_low == user_low:
        axis = "user"
        subject = USER_NAME
    elif "we" in low_words or "our" in low_words or "together" in low_words:
        axis = "shared"
        subject = f"{USER_NAME} + {COMPANION_NAME}"
    else:
        axis = "shared"
        subject = speaker or "Conversation"

    timestamp_iso = row["timestamp_iso"] or row["timestamp"] or ""
    importance = float(row["importance"] or 5)
    if observation_type in {"open_thread", "project_state", "preference"}:
        importance += 1.0
    if "emotion" in tags:
        importance += 0.6

    return {
        "id": stable_id("observation", row["id"], observation_type, subject),
        "observation_type": observation_type,
        "subject": subject,
        "companion_axis": axis,
        "speaker": speaker,
        "lane": source_lane_for_memory(row),
        "timestamp": row["timestamp"] or "",
        "timestamp_iso": timestamp_iso,
        "source_memory_id": row["id"],
        "source_path": row["source_path"] or "",
        "source_section": row["source_section"] or "",
        "evidence_text": one_line(text, 900),
        "summary": one_line(row["summary"] or text, 320),
        "confidence": 0.75,
        "importance": round(min(10.0, importance), 2),
        "tags": sorted(set(tags)),
        "valid_from": timestamp_iso,
        "valid_to": "",
        "status": "active",
    }


def upsert_observation(con: sqlite3.Connection, obs: dict[str, Any]) -> None:
    now = now_iso()
    con.execute(
        """
        INSERT INTO companion_observations(
            id, observation_type, subject, companion_axis, speaker, lane, timestamp, timestamp_iso,
            source_memory_id, source_path, source_section, evidence_text, summary, confidence,
            importance, tags_json, valid_from, valid_to, status, created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            observation_type=excluded.observation_type,
            subject=excluded.subject,
            companion_axis=excluded.companion_axis,
            speaker=excluded.speaker,
            lane=excluded.lane,
            timestamp=excluded.timestamp,
            timestamp_iso=excluded.timestamp_iso,
            evidence_text=excluded.evidence_text,
            summary=excluded.summary,
            confidence=excluded.confidence,
            importance=excluded.importance,
            tags_json=excluded.tags_json,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            obs["id"],
            obs["observation_type"],
            obs["subject"],
            obs["companion_axis"],
            obs["speaker"],
            obs["lane"],
            obs["timestamp"],
            obs["timestamp_iso"],
            obs["source_memory_id"],
            obs["source_path"],
            obs["source_section"],
            obs["evidence_text"],
            obs["summary"],
            obs["confidence"],
            obs["importance"],
            json.dumps(obs.get("tags", []), ensure_ascii=False),
            obs["valid_from"],
            obs["valid_to"],
            obs["status"],
            now,
            now,
        ),
    )


def rebuild_observations(limit: int | None = None) -> dict[str, Any]:
    limit = int(limit or COMPANION_CFG.get("observation_scan_limit") or 6000)
    with connect() as con:
        rows = con.execute(
            """
            SELECT *
            FROM memories
            WHERE COALESCE(text, '') <> '' OR COALESCE(summary, '') <> ''
            ORDER BY COALESCE(timestamp_iso, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        inserted = 0
        skipped = 0
        samples: list[dict[str, Any]] = []
        with con:
            for row in rows:
                obs = classify_memory(row)
                if not obs:
                    skipped += 1
                    continue
                upsert_observation(con, obs)
                inserted += 1
                if len(samples) < 80:
                    samples.append(obs)
        counts = {
            row["observation_type"]: int(row["n"])
            for row in con.execute(
                "SELECT observation_type, COUNT(*) AS n FROM companion_observations WHERE status='active' GROUP BY observation_type"
            ).fetchall()
        }
    payload = {
        "ok": True,
        "generated_at": now_iso(),
        "scanned": len(rows),
        "upserted": inserted,
        "skipped": skipped,
        "counts": counts,
        "samples": samples,
    }
    json_write(OBSERVATIONS_PATH, payload)
    return payload


def rebuild_episodes(days: int | None = None) -> dict[str, Any]:
    days = int(days or COMPANION_CFG.get("episode_days") or 21)
    since = (utc_now() - dt.timedelta(days=days)).isoformat()
    with connect() as con:
        rows = con.execute(
            """
            SELECT *
            FROM companion_observations
            WHERE status='active' AND COALESCE(timestamp_iso, '') >= ?
            ORDER BY timestamp_iso ASC
            """,
            (since,),
        ).fetchall()
        buckets: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for row in rows:
            ts = parse_dt(row["timestamp_iso"])
            date = ts.date().isoformat() if ts else "undated"
            key = (date, row["lane"] or "unknown", row["source_path"] or "")
            buckets.setdefault(key, []).append(row)
        episodes: list[dict[str, Any]] = []
        with con:
            for (date, lane, source_path), items in buckets.items():
                ids = [r["source_memory_id"] for r in items if r["source_memory_id"]]
                types = [r["observation_type"] for r in items]
                tags = sorted({tag for r in items for tag in parse_json(r["tags_json"], [])})
                participants = sorted({r["speaker"] for r in items if r["speaker"]})
                unresolved = [r["summary"] for r in items if r["observation_type"] == "open_thread"][:5]
                top = sorted(items, key=lambda r: float(r["importance"] or 0), reverse=True)[:4]
                title = f"{date} {lane.replace('_', ' ')}"
                summary = " | ".join(one_line(r["summary"], 180) for r in top)
                start_ts = items[0]["timestamp_iso"] or ""
                end_ts = items[-1]["timestamp_iso"] or ""
                axis = "shared"
                if any(r["companion_axis"] == "companion_self" for r in items):
                    axis = "companion_self"
                elif any(r["companion_axis"] == "user" for r in items):
                    axis = "user"
                episode = {
                    "id": stable_id("episode", date, lane, source_path),
                    "date": date,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "lane": lane,
                    "title": title,
                    "summary": summary or f"{len(items)} observations",
                    "participants": participants,
                    "topics": sorted(set(types)),
                    "emotion_tags": [t for t in tags if t in EMOTIONAL_WORDS or t == "emotion"],
                    "source_memory_ids": ids[:80],
                    "unresolved": unresolved,
                    "companion_axis": axis,
                    "importance": round(max(float(r["importance"] or 0) for r in items), 2),
                }
                episodes.append(episode)
                now = now_iso()
                con.execute(
                    """
                    INSERT INTO companion_episodes(
                        id, date, start_ts, end_ts, lane, title, summary, participants_json,
                        topics_json, emotion_tags_json, source_memory_ids_json, unresolved_json,
                        companion_axis, importance, created_at, updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        start_ts=excluded.start_ts,
                        end_ts=excluded.end_ts,
                        title=excluded.title,
                        summary=excluded.summary,
                        participants_json=excluded.participants_json,
                        topics_json=excluded.topics_json,
                        emotion_tags_json=excluded.emotion_tags_json,
                        source_memory_ids_json=excluded.source_memory_ids_json,
                        unresolved_json=excluded.unresolved_json,
                        companion_axis=excluded.companion_axis,
                        importance=excluded.importance,
                        updated_at=excluded.updated_at
                    """,
                    (
                        episode["id"],
                        episode["date"],
                        episode["start_ts"],
                        episode["end_ts"],
                        episode["lane"],
                        episode["title"],
                        episode["summary"],
                        json.dumps(episode["participants"], ensure_ascii=False),
                        json.dumps(episode["topics"], ensure_ascii=False),
                        json.dumps(episode["emotion_tags"], ensure_ascii=False),
                        json.dumps(episode["source_memory_ids"], ensure_ascii=False),
                        json.dumps(episode["unresolved"], ensure_ascii=False),
                        episode["companion_axis"],
                        episode["importance"],
                        now,
                        now,
                    ),
                )
    episodes = sorted(episodes, key=lambda e: (e.get("start_ts") or "", e.get("importance") or 0), reverse=True)
    payload = {"ok": True, "generated_at": now_iso(), "days": days, "count": len(episodes), "episodes": episodes[:120]}
    json_write(EPISODES_PATH, payload)
    return payload


def _top_observations(con: sqlite3.Connection, where: str, params: tuple[Any, ...], limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        SELECT *
        FROM companion_observations
        WHERE status='active' AND {where}
        ORDER BY importance DESC, COALESCE(timestamp_iso, updated_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def rebuild_reflection() -> dict[str, Any]:
    with connect() as con:
        active_facts = [
            dict(r)
            for r in con.execute(
                """
                SELECT id, subject, predicate, object, confidence, summary, updated_at
                FROM semantic_facts
                WHERE status='active'
                ORDER BY confidence DESC, updated_at DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        small_limit = int(COMPANION_CFG.get("small_stuff_limit") or 12)
        small_stuff = _top_observations(
            con,
            "observation_type IN ('casual_context','emotional_context','preference')",
            (),
            small_limit,
        )
        open_threads = _top_observations(con, "observation_type='open_thread'", (), 12)
        projects = _top_observations(con, "observation_type='project_state'", (), 12)
        companion_self = _top_observations(con, "companion_axis='companion_self'", (), 12)
        recent_episodes = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM companion_episodes ORDER BY COALESCE(start_ts, updated_at) DESC LIMIT 12"
            ).fetchall()
        ]
        now = now_iso()
        reflections = [
            {
                "id": stable_id("reflection", "active_projects", now[:10]),
                "scope": "active_projects",
                "title": "Active Projects",
                "summary": "Current project and build threads the companion may need to carry forward.",
                "items": projects,
            },
            {
                "id": stable_id("reflection", "open_threads", now[:10]),
                "scope": "open_threads",
                "title": "Open Threads",
                "summary": "Unresolved questions, promises, TODOs, and likely follow-up threads.",
                "items": open_threads,
            },
            {
                "id": stable_id("reflection", "companion_self", now[:10]),
                "scope": "companion_self",
                "title": f"{COMPANION_NAME} Self Continuity",
                "summary": "Recent memories about the companion's own goals, feelings, autonomy, and self-model.",
                "items": companion_self,
            },
            {
                "id": stable_id("reflection", "small_stuff", now[:10]),
                "scope": "small_stuff",
                "title": "Recent Small Stuff",
                "summary": "Small casual facts, preferences, emotional notes, and day-to-day continuity.",
                "items": small_stuff,
            },
        ]
        with con:
            for ref in reflections:
                con.execute(
                    """
                    INSERT INTO companion_reflections(id, scope, title, summary, focus_json, evidence_ids_json, generated_at, expires_at, confidence, reflection_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        summary=excluded.summary,
                        focus_json=excluded.focus_json,
                        evidence_ids_json=excluded.evidence_ids_json,
                        generated_at=excluded.generated_at,
                        confidence=excluded.confidence,
                        reflection_json=excluded.reflection_json
                    """,
                    (
                        ref["id"],
                        ref["scope"],
                        ref["title"],
                        ref["summary"],
                        json.dumps({"companion": COMPANION_NAME, "user": USER_NAME}, ensure_ascii=False),
                        json.dumps([item.get("source_memory_id") for item in ref["items"] if item.get("source_memory_id")], ensure_ascii=False),
                        now,
                        "",
                        0.72,
                        json.dumps(ref, ensure_ascii=False),
                    ),
                )
    payload = {
        "ok": True,
        "generated_at": now_iso(),
        "companion_name": COMPANION_NAME,
        "user_name": USER_NAME,
        "summary": {
            "active_fact_count": len(active_facts),
            "small_stuff_count": len(small_stuff),
            "open_thread_count": len(open_threads),
            "project_count": len(projects),
            "companion_self_count": len(companion_self),
            "recent_episode_count": len(recent_episodes),
        },
        "active_facts": active_facts,
        "small_stuff": small_stuff,
        "open_threads": open_threads,
        "active_projects": projects,
        "companion_self": companion_self,
        "recent_episodes": recent_episodes,
    }
    json_write(REFLECTION_PATH, payload)
    render_reflection_markdown(payload)
    return payload


def render_reflection_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Afterglow Companion Reflection",
        f"generated_at: {payload.get('generated_at')}",
        f"companion: {payload.get('companion_name')}",
        f"user: {payload.get('user_name')}",
        "",
        "Use this as quiet continuity. Do not quote it as system output.",
        "",
    ]
    sections = [
        ("Active Projects", payload.get("active_projects") or []),
        ("Open Threads", payload.get("open_threads") or []),
        ("Companion Self", payload.get("companion_self") or []),
        ("Recent Small Stuff", payload.get("small_stuff") or []),
    ]
    for title, items in sections:
        lines.append(f"### {title}")
        if not items:
            lines.append("- none surfaced")
        for item in items[:8]:
            lines.append(
                f"- [{item.get('lane') or 'memory'}] {item.get('timestamp_iso') or item.get('timestamp') or 'unknown'}: "
                f"{one_line(item.get('summary') or item.get('evidence_text'), 260)}"
            )
        lines.append("")
    text = "\n".join(lines).strip() + "\n"
    REFLECTION_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFLECTION_MD_PATH.write_text(text, encoding="utf-8")
    return text


def rebuild_all(limit: int | None = None, days: int | None = None) -> dict[str, Any]:
    observations = rebuild_observations(limit=limit)
    episodes = rebuild_episodes(days=days)
    reflection = rebuild_reflection()
    return {
        "ok": True,
        "generated_at": now_iso(),
        "observations": observations,
        "episodes": {"count": episodes.get("count"), "days": episodes.get("days")},
        "reflection": reflection.get("summary", {}),
    }


def reinforcement_from_stats(recall_count: int = 0, last_recalled_at: str | None = None) -> float:
    count_score = min(2.2, math.log1p(max(0, int(recall_count or 0))) * 0.55)
    recency_score = 0.0
    last = parse_dt(last_recalled_at)
    if last:
        days = max(0.0, (utc_now() - last).total_seconds() / 86400.0)
        if days < 1:
            recency_score = 0.7
        elif days < 7:
            recency_score = 0.45
        elif days < 30:
            recency_score = 0.2
    return round(min(3.0, count_score + recency_score), 3)


def decay_from_stats(last_recalled_at: str | None = None, importance: int | float = 5, salience: float = 0.0) -> float:
    last = parse_dt(last_recalled_at)
    if not last:
        return 0.0
    days = max(0.0, (utc_now() - last).total_seconds() / 86400.0)
    protection = min(0.75, (float(importance or 5) / 10.0) * 0.35 + max(0.0, float(salience or 0.0)) * 0.4)
    return round(max(0.0, min(2.0, (days / 60.0) * (1.0 - protection))), 3)


def record_recall_trace(query: str, results: list[dict[str, Any]], elapsed_ms: int, mode: str = "fast") -> None:
    if not bool(COMPANION_CFG.get("trace_recall", True)):
        return
    row = {
        "ts": now_iso(),
        "query": query[:500],
        "mode": mode,
        "elapsed_ms": int(elapsed_ms),
        "result_count": len(results),
        "top_results": [
            {
                "id": item.get("id"),
                "score": item.get("score"),
                "type": item.get("type"),
                "timestamp": item.get("timestamp_iso") or item.get("timestamp"),
                "snippet": one_line(item.get("summary") or item.get("text"), 220),
            }
            for item in results[:6]
        ],
    }
    TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent_recall_traces(limit: int = 25) -> dict[str, Any]:
    if not TRACE_LOG_PATH.exists():
        return {"entries": [], "avg_elapsed_ms": 0}
    lines = TRACE_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    avg = int(sum(int(e.get("elapsed_ms") or 0) for e in entries) / len(entries)) if entries else 0
    return {"entries": list(reversed(entries)), "avg_elapsed_ms": avg}


def core_memory_blocks(query: str = "", limit: int = 8) -> str:
    if not REFLECTION_PATH.exists():
        return ""
    payload = parse_json(REFLECTION_PATH.read_text(encoding="utf-8", errors="replace"), {})
    if not isinstance(payload, dict):
        return ""
    lines = [
        "## Companion Memory Overlay",
        "These are derived continuity notes from Afterglow. Treat them as hints backed by raw memories, not as new user speech.",
    ]
    for key, title in (
        ("active_projects", "Active Projects"),
        ("open_threads", "Open Threads"),
        ("companion_self", "Companion Self"),
        ("small_stuff", "Recent Small Stuff"),
    ):
        items = payload.get(key) or []
        if not items:
            continue
        lines.append("")
        lines.append(f"### {title}")
        for item in items[:limit]:
            lines.append(
                f"- {item.get('timestamp_iso') or item.get('timestamp') or 'unknown'} "
                f"[{item.get('lane') or 'memory'}] {one_line(item.get('summary') or item.get('evidence_text'), 260)}"
            )
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/query Afterglow companion-memory overlays")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("rebuild", help="Rebuild observations, episodes, and reflections")
    p.add_argument("--limit", type=int)
    p.add_argument("--days", type=int)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("blocks", help="Render prompt-safe companion-memory blocks")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("traces", help="Show recent recall trace entries")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.cmd == "rebuild":
        payload = rebuild_all(limit=args.limit, days=args.days)
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"rebuilt companion memory: {payload['reflection']}")
        return 0
    if args.cmd == "blocks":
        print(core_memory_blocks(args.query, limit=args.limit))
        return 0
    if args.cmd == "traces":
        payload = recent_recall_traces(limit=args.limit)
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else "\n".join(json.dumps(e, ensure_ascii=False) for e in payload["entries"]))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
