#!/usr/bin/env python3
"""Afterglow memory core for OpenClaw.

This is a self-contained, local SQLite memory layer. It is intentionally
additive: imports never delete source files or old memories, and every imported
item keeps a source pointer so recall can be audited later.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable


def _configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


_configure_utf8_stdio()


def _default_workspace() -> Path:
    return Path(__file__).resolve().parents[1]


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE") or _default_workspace()).resolve()
STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR") or WORKSPACE.parent).resolve()
SESSIONS_DIR = Path(os.environ.get("OPENCLAW_SESSIONS_DIR") or STATE_DIR / "agents" / "main" / "sessions").resolve()
BRAIN = WORKSPACE / "brain"
DB_PATH = BRAIN / "memory_index" / "afterglow.sqlite"
CURRENT_RECALL = BRAIN / "current_recall.json"
RESPONSE_CONTEXT = BRAIN / "current_response_context.json"
INBOUND_MESSAGE = BRAIN / "current_inbound_message.txt"
CONVERSATION_ARCHIVE = BRAIN / "conversation_archive" / "messages.jsonl"
IMPORT_REPORT = BRAIN / "afterglow_import_report.json"
LOG_PATH = WORKSPACE / "logs" / "afterglow.log"
SEMANTIC_FACT_PROMOTION_AUDIT = WORKSPACE / "logs" / "semantic_fact_promotion_audit.jsonl"
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc

DB_VERSION = 1

STOP_WORDS = {
    "the", "and", "that", "with", "from", "this", "your", "have", "what", "when",
    "just", "like", "about", "there", "would", "could", "should", "were", "been",
    "into", "because", "while", "yeah", "okay", "good", "want", "think", "know",
    "going", "really", "actually", "something", "everything", "anything", "here",
    "will", "make", "take", "being", "does", "done", "working", "looking", "getting",
    "trying", "thing", "things", "need", "check", "look", "message", "messages",
    "session", "sessions", "user", "assistant", "source", "reply", "context",
}

EMOTION_TAGS = {
    "affection": ["love", "care", "appreciate", "sweet", "close", "miss"],
    "joy": ["happy", "excited", "fun", "laugh", "proud", "yay"],
    "frustration": ["frustrated", "broken", "stuck", "wrong", "error", "annoy"],
    "sadness": ["sad", "hurt", "lonely", "cry", "grief"],
    "fear": ["scared", "anxious", "worried", "panic"],
    "curiosity": ["wonder", "curious", "explore", "why", "how"],
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {message}\n")
    except Exception:
        pass


def stable_id(*parts: Any, length: int = 24) -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:length]


def one_line(text: str, limit: int = 300) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 1)].rstrip() + "..."


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=ON")
    ensure_schema(con)
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_sources (
            source_path TEXT PRIMARY KEY,
            source_kind TEXT,
            fingerprint TEXT,
            size_bytes INTEGER,
            mtime REAL,
            imported_at TEXT NOT NULL,
            entry_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            fingerprint TEXT,
            type TEXT,
            timestamp TEXT,
            timestamp_iso TEXT,
            importance INTEGER,
            summary TEXT,
            text TEXT,
            source_kind TEXT,
            source_path TEXT,
            source_section TEXT,
            entry_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_fingerprint_unique
            ON memories(fingerprint) WHERE fingerprint IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
        CREATE INDEX IF NOT EXISTS idx_memories_timestamp_iso ON memories(timestamp_iso);
        CREATE INDEX IF NOT EXISTS idx_memories_source_path ON memories(source_path);
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            id UNINDEXED,
            summary,
            text,
            keywords,
            topics,
            entities,
            tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT NOT NULL,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(memory_id, model),
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS memory_emotion_profiles (
            memory_id TEXT PRIMARY KEY,
            valence REAL,
            arousal REAL,
            salience REAL,
            tags_json TEXT,
            drives_json TEXT,
            source_strength REAL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS memory_recall_stats (
            memory_id TEXT PRIMARY KEY,
            first_recalled_at TEXT NOT NULL,
            last_recalled_at TEXT NOT NULL,
            recall_count INTEGER NOT NULL DEFAULT 0,
            total_score REAL NOT NULL DEFAULT 0,
            last_score REAL NOT NULL DEFAULT 0,
            last_lane TEXT,
            reinforcement REAL NOT NULL DEFAULT 0,
            decay_score REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_entities (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            entity_type TEXT,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            privacy_level TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_entities_name ON semantic_entities(canonical_name);
        CREATE TABLE IF NOT EXISTS semantic_facts (
            id TEXT PRIMARY KEY,
            subject_entity_id TEXT,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            object_entity_id TEXT,
            object_type TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            confidence REAL NOT NULL DEFAULT 0.75,
            privacy_level TEXT,
            privacy_labels_json TEXT NOT NULL DEFAULT '[]',
            event_time TEXT,
            valid_from TEXT,
            valid_to TEXT,
            summary TEXT,
            text TEXT NOT NULL,
            contextual_text TEXT,
            source_ids_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            supersedes_fact_id TEXT,
            contradicted_by_fact_id TEXT,
            memory_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_facts_subject ON semantic_facts(subject);
        CREATE INDEX IF NOT EXISTS idx_semantic_facts_predicate ON semantic_facts(predicate);
        CREATE INDEX IF NOT EXISTS idx_semantic_facts_status ON semantic_facts(status);
        CREATE VIRTUAL TABLE IF NOT EXISTS semantic_facts_fts USING fts5(
            id UNINDEXED,
            subject,
            predicate,
            object,
            summary,
            text,
            contextual_text,
            tags,
            tokenize='unicode61'
        );
        """
    )
    con.execute(
        "INSERT OR REPLACE INTO metadata(key, value_json) VALUES('schema_version', ?)",
        (json.dumps(DB_VERSION),),
    )


def parse_time(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if n > 10_000_000_000:
            n /= 1000.0
        if n > 0:
            return dt.datetime.fromtimestamp(n, tz=dt.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_time(int(text))
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%m/%d/%Y", "%I:%M %p ET"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            if parsed.year == 1900:
                today = dt.datetime.now(LOCAL_TZ)
                parsed = parsed.replace(year=today.year, month=today.month, day=today.day)
            return parsed.replace(tzinfo=LOCAL_TZ).astimezone(dt.timezone.utc)
        except Exception:
            continue
    return None


def iso_for(value: Any, fallback_path: Path | None = None) -> str:
    parsed = parse_time(value)
    if parsed:
        return parsed.isoformat().replace("+00:00", "Z")
    if fallback_path and fallback_path.exists():
        return dt.datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return now_iso()


def filename_date(path: Path) -> str | None:
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})(?:[-_T](\d{2})(\d{2})?)?", path.name)
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    if hh:
        return f"{y}-{mo}-{d}T{hh}:{mm or '00'}:00"
    return f"{y}-{mo}-{d}"


def tokens_for(text: str, limit: int = 16) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"[a-zA-Z0-9_@#.'-]{3,}", (text or "").lower()):
        tok = raw.strip(".-'_")
        if len(tok) < 3 or tok in STOP_WORDS:
            continue
        if tok not in out:
            out.append(tok)
        if len(out) >= limit:
            break
    return out


def make_keywords(text: str) -> list[str]:
    return tokens_for(text, limit=24)


def extract_topics_from_lines(lines: list[str], limit: int = 6) -> list[str]:
    text = " ".join(lines)
    phrases = []
    for phrase in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3}\b", text):
        if len(phrase) > 2 and phrase.lower() not in STOP_WORDS:
            phrases.append(phrase)
    words = tokens_for(text, limit=limit * 3)
    merged: list[str] = []
    for item in phrases + words:
        low = item.lower()
        if low not in {x.lower() for x in merged}:
            merged.append(item)
        if len(merged) >= limit:
            break
    return merged or ["general chat"]


def infer_importance(text: str, memory_type: str = "note") -> int:
    low = (text or "").lower()
    score = 5
    if memory_type in {"semantic_fact", "canon_memory"}:
        score += 2
    if any(k in low for k in ("remember", "canon", "important", "never forget", "always", "promise")):
        score += 2
    if any(k in low for k in ("love", "grief", "hurt", "scared", "proud", "family", "name is", "called")):
        score += 1
    if any(k in low for k in ("debug", "stack trace", "npm", "gradle", "error log")):
        score -= 1
    return max(1, min(10, score))


def emotion_profile(text: str) -> dict[str, Any]:
    low = (text or "").lower()
    tags = [tag for tag, words in EMOTION_TAGS.items() if any(w in low for w in words)]
    salience = min(1.0, 0.15 + 0.14 * len(tags) + (0.15 if re.search(r"\b(love|hurt|important|remember|never forget)\b", low) else 0))
    valence = 0.0
    if any(t in tags for t in ("affection", "joy", "curiosity")):
        valence += 0.35
    if any(t in tags for t in ("frustration", "sadness", "fear")):
        valence -= 0.35
    arousal = 0.25 + (0.12 * len(tags))
    return {
        "valence": round(max(-1.0, min(1.0, valence)), 3),
        "arousal": round(max(0.0, min(1.0, arousal)), 3),
        "salience": round(salience, 3),
        "tags": tags,
        "drives": {},
        "source_strength": 0.7 if tags else 0.35,
    }


def strip_transport(text: str) -> str:
    text = str(text or "")
    m = re.search(r"<(?:user|human|companion_user|turn)_message\b[^>]*>(.*?)</(?:user|human|companion_user|turn)_message>", text, flags=re.S | re.I)
    if m:
        return m.group(1).strip()
    text = re.sub(r"<(?:bridge|system|transport)_system_context\b[^>]*>.*?</(?:bridge|system|transport)_system_context>", "", text, flags=re.S | re.I)
    text = re.sub(r"(?:Conversation info|Sender) \(untrusted metadata\):\s*```json\s*\{.*?\}\s*```\s*", "", text, flags=re.S)
    text = re.sub(r"<<<EXTERNAL_UNTRUSTED_CONTENT.*?<<<END_EXTERNAL_UNTRUSTED_CONTENT.*?>>>", "", text, flags=re.S)
    return text.strip()


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return ""


def canonical_entry(entry: dict[str, Any]) -> dict[str, Any]:
    text = strip_transport(str(entry.get("text") or entry.get("raw_event") or ""))
    summary = one_line(str(entry.get("summary") or text), 420)
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    source_path = str(source.get("path") or entry.get("source_path") or "unknown")
    source_section = str(source.get("section") or entry.get("source_section") or "")
    source_kind = str(source.get("kind") or entry.get("source_kind") or "import")
    timestamp = str(entry.get("timestamp") or entry.get("timestamp_label") or "")
    timestamp_iso = iso_for(entry.get("timestamp_iso") or entry.get("ts") or entry.get("timestamp"), Path(source_path) if source_path != "unknown" else None)
    memory_type = str(entry.get("type") or "note")
    fingerprint = entry.get("fingerprint") or stable_id(source_path, source_section, timestamp_iso, text[:1000])
    memory_id = str(entry.get("id") or f"mem_{fingerprint}")
    keywords = entry.get("keywords") if isinstance(entry.get("keywords"), list) else make_keywords(f"{summary}\n{text}")
    topics = entry.get("topics") if isinstance(entry.get("topics"), list) else extract_topics_from_lines([summary, text])
    entities = entry.get("entities") if isinstance(entry.get("entities"), list) else []
    out = {
        "id": memory_id,
        "fingerprint": fingerprint,
        "type": memory_type,
        "timestamp": timestamp or timestamp_iso,
        "timestamp_iso": timestamp_iso,
        "importance": int(entry.get("importance") or infer_importance(text, memory_type)),
        "summary": summary,
        "text": text,
        "source_kind": source_kind,
        "source_path": source_path,
        "source_section": source_section,
        "keywords": keywords,
        "topics": topics,
        "entities": entities,
        "source": {
            "path": source_path,
            "section": source_section,
            "kind": source_kind,
            **{k: v for k, v in source.items() if k not in {"path", "section", "kind"}},
        },
    }
    return out


def upsert_memory(con: sqlite3.Connection, entry: dict[str, Any]) -> bool:
    e = canonical_entry(entry)
    if not e["text"].strip():
        return False
    now = now_iso()
    existing = con.execute("SELECT id FROM memories WHERE fingerprint=?", (e["fingerprint"],)).fetchone()
    if existing:
        e["id"] = existing["id"]
    entry_json = json.dumps(e, ensure_ascii=False, separators=(",", ":"))
    con.execute(
        """
        INSERT INTO memories(
            id, fingerprint, type, timestamp, timestamp_iso, importance, summary,
            text, source_kind, source_path, source_section, entry_json, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            fingerprint=excluded.fingerprint,
            type=excluded.type,
            timestamp=excluded.timestamp,
            timestamp_iso=excluded.timestamp_iso,
            importance=excluded.importance,
            summary=excluded.summary,
            text=excluded.text,
            source_kind=excluded.source_kind,
            source_path=excluded.source_path,
            source_section=excluded.source_section,
            entry_json=excluded.entry_json,
            updated_at=excluded.updated_at
        """,
        (
            e["id"], e["fingerprint"], e["type"], e["timestamp"], e["timestamp_iso"],
            e["importance"], e["summary"], e["text"], e["source_kind"], e["source_path"],
            e["source_section"], entry_json, now,
        ),
    )
    con.execute("DELETE FROM memories_fts WHERE id=?", (e["id"],))
    con.execute(
        "INSERT INTO memories_fts(id, summary, text, keywords, topics, entities) VALUES(?, ?, ?, ?, ?, ?)",
        (e["id"], e["summary"], e["text"], " ".join(e["keywords"]), " ".join(e["topics"]), " ".join(map(str, e["entities"]))),
    )
    prof = emotion_profile(f"{e['summary']}\n{e['text']}")
    con.execute(
        """
        INSERT INTO memory_emotion_profiles(memory_id, valence, arousal, salience, tags_json, drives_json, source_strength, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_id) DO UPDATE SET
            valence=excluded.valence, arousal=excluded.arousal, salience=excluded.salience,
            tags_json=excluded.tags_json, drives_json=excluded.drives_json,
            source_strength=excluded.source_strength, updated_at=excluded.updated_at
        """,
        (
            e["id"], prof["valence"], prof["arousal"], prof["salience"],
            json.dumps(prof["tags"], ensure_ascii=False), json.dumps(prof["drives"], ensure_ascii=False),
            prof["source_strength"], now,
        ),
    )
    return existing is None


def chunk_text(text: str, size: int = 5000, overlap: int = 350) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            split = text.rfind("\n\n", start, end)
            if split > start + size // 2:
                end = split
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def markdown_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            return clean.lstrip("#").strip() or path.stem
        if clean:
            return one_line(clean, 160)
    return path.stem


def import_text_file(con: sqlite3.Connection, path: Path, source_kind: str = "local_memory") -> int:
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as exc:
        log(f"import_text_file failed path={path} error={exc}")
        return 0
    if not raw.strip():
        return 0
    title = markdown_title(raw, path)
    ts = filename_date(path) or path.stat().st_mtime
    chunks = chunk_text(raw)
    added = 0
    for idx, chunk in enumerate(chunks):
        entry = {
            "type": "document" if len(chunks) > 1 else "note",
            "timestamp": str(ts),
            "timestamp_iso": iso_for(ts, path),
            "summary": title if len(chunks) == 1 else f"{title} [chunk {idx + 1}/{len(chunks)}]",
            "text": chunk,
            "importance": infer_importance(chunk, "note"),
            "source": {"path": str(path), "section": f"chunk:{idx}", "kind": source_kind},
        }
        if upsert_memory(con, entry):
            added += 1
    con.execute(
        """
        INSERT OR REPLACE INTO import_sources(source_path, source_kind, fingerprint, size_bytes, mtime, imported_at, entry_count)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path), source_kind, stable_id(path, path.stat().st_size, path.stat().st_mtime),
            path.stat().st_size, path.stat().st_mtime, now_iso(), len(chunks),
        ),
    )
    return added


def session_memory_entry(
    path: Path,
    idx: int,
    role: str,
    text: str,
    ts: Any,
    source_kind: str,
    section: str,
    extra_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    speaker = "Assistant" if role == "assistant" else "User"
    timestamp_iso = iso_for(ts, path)
    entry = {
        "type": "conversation",
        "timestamp": str(ts),
        "timestamp_iso": timestamp_iso,
        "summary": f"{speaker}: {one_line(text, 220)}",
        "text": f"{speaker}: {text}",
        "importance": infer_importance(text, "conversation"),
        "fingerprint": stable_id("openclaw-message", role, timestamp_iso, text[:1200]),
        "source": {
            "path": str(path),
            "section": section,
            "kind": source_kind,
            "role": role,
            "message_index": idx,
            **(extra_source or {}),
        },
    }
    return entry


def parse_session_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return rows
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "model.completed" and isinstance(obj.get("data"), dict):
            data = obj.get("data") or {}
            source_kind = "openclaw_trajectory"
            for msg_idx, msg in enumerate(data.get("messagesSnapshot") or []):
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role") or "")
                if role not in {"user", "assistant"}:
                    continue
                text = strip_transport(content_text(msg.get("content")))
                if len(text.strip()) < 2:
                    continue
                ts = msg.get("timestamp") or obj.get("ts") or path.stat().st_mtime
                rows.append(session_memory_entry(
                    path,
                    idx,
                    role,
                    text,
                    ts,
                    source_kind,
                    f"line:{idx}:snapshot:{msg_idx}",
                    {"trace_type": obj.get("type"), "session_id": obj.get("sessionId"), "run_id": obj.get("runId")},
                ))
            for msg_idx, assistant_text in enumerate(data.get("assistantTexts") or []):
                text = strip_transport(content_text(assistant_text))
                if len(text.strip()) < 2:
                    continue
                ts = obj.get("ts") or path.stat().st_mtime
                rows.append(session_memory_entry(
                    path,
                    idx,
                    "assistant",
                    text,
                    ts,
                    source_kind,
                    f"line:{idx}:assistant_text:{msg_idx}",
                    {"trace_type": obj.get("type"), "session_id": obj.get("sessionId"), "run_id": obj.get("runId")},
                ))
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = str(msg.get("role") or obj.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        text = strip_transport(content_text(msg.get("content") if "content" in msg else obj.get("content")))
        if len(text.strip()) < 2:
            continue
        ts = obj.get("ts") or obj.get("timestamp") or msg.get("timestamp") or path.stat().st_mtime
        rows.append(session_memory_entry(path, idx, role, text, ts, "openclaw_session", f"line:{idx}"))
    return rows


def iter_session_files() -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    files: dict[str, Path] = {}
    for pattern in ("*.jsonl", "*.jsonl.reset.*"):
        for path in SESSIONS_DIR.glob(pattern):
            if not path.is_file():
                continue
            if path.name in {".usage-cost-cache.json", "sessions.json"}:
                continue
            if path.name.endswith(".trajectory-path.json"):
                continue
            files[str(path)] = path
    return sorted(files.values(), key=lambda p: p.stat().st_mtime)


def import_session_file(con: sqlite3.Connection, path: Path) -> int:
    size = path.stat().st_size
    mtime = path.stat().st_mtime
    fingerprint = stable_id(path, size, mtime)
    try:
        prior = con.execute("SELECT fingerprint FROM import_sources WHERE source_path=?", (str(path),)).fetchone()
        if prior and prior["fingerprint"] == fingerprint:
            return 0
    except Exception:
        pass
    rows = parse_session_file(path)
    added = 0
    archive_rows = []
    for row in rows:
        if upsert_memory(con, row):
            added += 1
        archive_rows.append({
            "id": stable_id(path, row["source"]["section"], row["text"][:200], length=20),
            "thread_id": stable_id(path, length=16),
            "timestamp": row["timestamp_iso"],
            "source_path": str(path),
            "role": row["source"].get("role"),
            "text": row["text"],
            "archived_at": now_iso(),
        })
    if archive_rows:
        append_jsonl(CONVERSATION_ARCHIVE, archive_rows)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO import_sources(source_path, source_kind, fingerprint, size_bytes, mtime, imported_at, entry_count)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path), "openclaw_trajectory" if path.name.endswith(".trajectory.jsonl") else "openclaw_session", fingerprint,
                size, mtime, now_iso(), len(rows),
            ),
        )
    except Exception:
        pass
    return added


def iter_local_memory_files() -> Iterable[Path]:
    roots = [
        WORKSPACE / "memory",
        WORKSPACE / ".brain-stream-queue.disabled",
    ]
    extras = [
        WORKSPACE / "MEMORY.md",
        WORKSPACE / "pending_brain_writes.md",
        WORKSPACE / "USER.md",
        WORKSPACE / "IDENTITY.md",
        WORKSPACE / "SOUL.md",
    ]
    for root in roots:
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".jsonl"}:
                    yield path
    for path in extras:
        if path.exists():
            yield path


def import_local(con: sqlite3.Connection, include_sessions: bool = True, max_session_files: int | None = None) -> dict[str, Any]:
    stats = {"memory_files": 0, "memory_entries_added": 0, "session_files": 0, "session_entries_added": 0}
    for path in iter_local_memory_files():
        stats["memory_files"] += 1
        kind = "hindsight_queue" if ".brain-stream-queue" in str(path) or "pending_brain" in path.name else "local_memory"
        stats["memory_entries_added"] += import_text_file(con, path, source_kind=kind)
    if include_sessions and SESSIONS_DIR.exists():
        session_files = iter_session_files()
        if max_session_files:
            session_files = session_files[-max_session_files:]
        for path in session_files:
            stats["session_files"] += 1
            stats["session_entries_added"] += import_session_file(con, path)
    return stats


def import_hindsight_export(con: sqlite3.Connection, path: Path) -> dict[str, int]:
    stats = {"objects_seen": 0, "entries_added": 0}
    data = load_json(path, None)
    if data is None:
        return stats

    def walk(obj: Any, trail: str = "") -> Iterable[dict[str, Any]]:
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                yield from walk(item, f"{trail}/{i}")
        elif isinstance(obj, dict):
            text = obj.get("content") or obj.get("text") or obj.get("memory") or obj.get("body")
            summary = obj.get("summary") or obj.get("title") or obj.get("name")
            if text or summary:
                yield {
                    "type": "hindsight_memory",
                    "timestamp": obj.get("created_at") or obj.get("updated_at") or obj.get("timestamp") or "",
                    "timestamp_iso": obj.get("created_at") or obj.get("timestamp") or "",
                    "summary": str(summary or one_line(str(text), 220)),
                    "text": str(text or summary),
                    "importance": int(obj.get("importance") or obj.get("score") or 7) if str(obj.get("importance") or obj.get("score") or "7").replace(".", "", 1).isdigit() else 7,
                    "source": {
                        "path": str(path),
                        "section": trail or str(obj.get("id") or obj.get("memory_id") or ""),
                        "kind": "hindsight_export",
                        "external_id": obj.get("id") or obj.get("memory_id") or obj.get("document_id"),
                    },
                }
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    yield from walk(value, f"{trail}/{key}")

    for entry in walk(data):
        stats["objects_seen"] += 1
        if upsert_memory(con, entry):
            stats["entries_added"] += 1
    return stats


FACT_PATTERNS = [
    re.compile(r"\bremember(?: this| that)?:?\s+(?P<object>.{8,240})", re.I),
    re.compile(r"\b(?P<subject>[A-Z][A-Za-z0-9 _'-]{1,50})\s+(?:is called|is named|name is)\s+(?P<object>[^.\n]{2,120})", re.I),
    re.compile(r"\b(?P<subject>[A-Z][A-Za-z0-9 _'-]{1,50})\s+(?P<predicate>likes|loves|hates|prefers|needs|wants)\s+(?P<object>[^.\n]{3,160})", re.I),
    re.compile(r"\b(?P<subject>[A-Z][A-Za-z0-9 _'-]{1,50})\s+(?:is|are|was|were)\s+(?P<object>[^.\n]{3,160})", re.I),
]


def normalize_predicate(raw: str | None, remembered: bool = False) -> str:
    if remembered:
        return "remembered"
    value = (raw or "is").lower().replace(" ", "_")
    return {
        "loves": "likes",
        "hates": "dislikes",
        "prefers": "prefers",
        "needs": "needs",
        "wants": "wants",
    }.get(value, value)


SYSTEM_PROMPT_LEAK_RE = re.compile(
    r"(<(?:bridge|system|transport)_system_context\b|</(?:bridge|system|transport)_system_context>|"
    r"<joey_message\b|</joey_message>|<user_message\b|</user_message>|"
    r"\[text-thinking-level:|\[openclaw-thinking:|text thinking guidance:|"
    r"this is bridge/system context|it is not .* speaking|do not quote it|"
    r"<<<external_untrusted_content|available tool|available command|tools\.md)",
    re.I | re.S,
)

OPERATIONAL_CHATTER_RE = re.compile(
    r"\b(api[_ -]?key|secret token|bearer token|authorization header|database is locked|"
    r"traceback|stack trace|py_compile|regression test|gate timed out|context window|"
    r"returned an empty reply|assistant turn failed|reset recovery|http 5\d\d|websocket|"
    r"cron|daemon|systemd|sqlite|jsonl|openclaw status)\b",
    re.I,
)

COMPANION_KEEP_RE = re.compile(
    r"\b(joey|user|friend|companion|partner|likes|loves|prefers|needs|wants|"
    r"birthday|name is|called|remember|canon|important|always|never|promise|family|"
    r"project|working on|relationship|boundary)\b",
    re.I,
)


def normalize_fact_tag(value: Any) -> str:
    tag = re.sub(r"[^a-z0-9_:-]+", "_", str(value or "").lower()).strip("_")
    return tag[:64]


def normalize_fact_tags(fact: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for value in fact.get("tags") or []:
        tag = normalize_fact_tag(value)
        if tag and tag not in tags:
            tags.append(tag)
    memory_class = normalize_fact_tag(fact.get("memory_class"))
    durability = normalize_fact_tag(fact.get("durability"))
    if memory_class and memory_class not in tags:
        tags.append(memory_class)
    if durability and f"durability:{durability}" not in tags:
        tags.append(f"durability:{durability}")
    if "hindsight_plus" not in tags:
        tags.append("hindsight_plus")
    return tags


def strip_speaker_prefix(line: str) -> tuple[str, str]:
    m = re.match(r"^\s*(?P<speaker>[A-Za-z][A-Za-z0-9 _.'-]{0,40})\s*:\s*(?P<body>.+)$", str(line or ""), flags=re.S)
    if not m:
        return "", str(line or "").strip()
    speaker = one_line(m.group("speaker"), 60)
    return speaker, m.group("body").strip()


def infer_source_lane(source_id: str, text: str = "") -> str:
    low = f"{source_id} {text}".lower()
    for lane in ("discord", "call_ella", "phone", "watch", "voice", "text", "pulse", "diary", "hindsight"):
        if lane in low:
            return lane
    return "unknown"


def infer_memory_class(subject: str, predicate: str, obj: str, text: str, remembered: bool = False) -> str:
    low = f"{subject} {predicate} {obj} {text}".lower()
    if remembered or "remember" in low or "canon" in low or "important" in low:
        return "explicit_memory"
    if predicate in {"likes", "prefers", "dislikes"}:
        return "preference"
    if predicate in {"needs", "wants"}:
        return "need_or_goal"
    if "name is" in low or "called" in low or "birthday" in low:
        return "identity"
    if any(k in low for k in ("relationship", "friend", "partner", "family", "daughter", "son", "sister", "brother")):
        return "relationship"
    if any(k in low for k in ("project", "working on", "building", "app", "script", "repo", "feature")):
        return "project_state"
    if any(k in low for k in ("boundary", "never", "always", "do not", "don't")):
        return "boundary"
    return "general_fact"


def infer_fact_durability(memory_class: str, predicate: str, text: str) -> str:
    low = text.lower()
    if "never forget" in low or "always remember" in low or memory_class == "explicit_memory":
        return "user_marked"
    if memory_class in {"identity", "relationship", "boundary", "preference"}:
        return "stable"
    if predicate in {"needs", "wants"} or memory_class == "project_state":
        return "until_changed"
    return "observed"


def fact_contextual_text(fact: dict[str, Any]) -> str:
    parts = []
    for label, key in (
        ("Memory class", "memory_class"),
        ("Durability", "durability"),
        ("Speaker", "speaker"),
        ("Source lane", "source_lane"),
        ("Evidence", "evidence_quote"),
    ):
        value = fact.get(key)
        if value:
            parts.append(f"{label}: {one_line(str(value), 260)}")
    cues = fact.get("retrieval_cues") or []
    if cues:
        parts.append("Retrieval cues: " + ", ".join(map(str, cues[:12])))
    return "\n".join(parts)


def canonical_fact_parts(fact: dict[str, Any]) -> tuple[str, str, str]:
    subject = one_line(str(fact.get("subject") or "memory"), 120)
    predicate = re.sub(r"[^a-z0-9_]+", "_", str(fact.get("predicate") or "is").lower()).strip("_") or "is"
    obj = one_line(str(fact.get("object") or ""), 500)
    return subject, predicate, obj


def reject_fact_candidate_reason(fact: dict[str, Any]) -> str:
    subject, predicate, obj = canonical_fact_parts(fact)
    blob = "\n".join(
        str(fact.get(k) or "")
        for k in ("summary", "text", "contextual_text", "evidence_quote", "object", "subject")
    )
    low_subject = subject.lower().strip()
    if SYSTEM_PROMPT_LEAK_RE.search(blob):
        return "system_prompt_or_tool_context"
    if OPERATIONAL_CHATTER_RE.search(blob) and not COMPANION_KEEP_RE.search(blob):
        return "operational_chatter"
    if low_subject in {"system", "assistant", "tool", "developer", "openclaw", "bridge", "context"}:
        return "assistant_or_system_chatter"
    if predicate in {"is", "are", "was", "were"} and len(tokens_for(obj, limit=6)) < 2:
        return "too_generic"
    if re.search(r"\b(sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|password\s*[:=])", blob):
        return "secret_like_text"
    return ""


def existing_active_fact_id(con: sqlite3.Connection, fact: dict[str, Any]) -> str:
    subject, predicate, obj = canonical_fact_parts(fact)
    fact_id = str(fact.get("id") or "fact_" + stable_id(subject.lower(), predicate, obj.lower()))
    row = con.execute("SELECT id FROM semantic_facts WHERE id=? AND status='active'", (fact_id,)).fetchone()
    if row:
        return str(row["id"])
    row = con.execute(
        """
        SELECT id FROM semantic_facts
        WHERE lower(subject)=? AND lower(predicate)=? AND lower(object)=? AND status='active'
        LIMIT 1
        """,
        (subject.lower(), predicate.lower(), obj.lower()),
    ).fetchone()
    return str(row["id"]) if row else ""


def record_fact_promotion_audit(action: str, reason: str, fact: dict[str, Any], fact_id: str = "") -> None:
    row = {
        "timestamp": now_iso(),
        "action": action,
        "reason": reason,
        "fact_id": fact_id or fact.get("id") or "",
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "object": fact.get("object"),
        "confidence": fact.get("confidence"),
        "memory_class": fact.get("memory_class"),
        "durability": fact.get("durability"),
        "source_ids": fact.get("source_ids") or fact.get("source_turn_ids") or [],
        "evidence_quote": one_line(str(fact.get("evidence_quote") or fact.get("text") or ""), 300),
    }
    try:
        append_jsonl(SEMANTIC_FACT_PROMOTION_AUDIT, [row])
    except Exception:
        pass


def extract_fact_candidates(text: str, source_id: str = "") -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    source_lane = infer_source_lane(source_id, text)
    raw_text = str(text or "")
    has_user_message_wrapper = bool(re.search(r"<(?:user|human|companion_user|turn)_message\b", raw_text, flags=re.I))
    if SYSTEM_PROMPT_LEAK_RE.search(raw_text) and not has_user_message_wrapper:
        return []
    safe_text = strip_transport(raw_text)
    if SYSTEM_PROMPT_LEAK_RE.search(safe_text):
        return []
    for raw_line in safe_text.splitlines():
        line = one_line(raw_line, 500)
        if len(line) < 8:
            continue
        speaker, line = strip_speaker_prefix(line)
        if not line:
            continue
        low = line.lower()
        if not any(k in low for k in ("remember", "canon", "important", "always", "never", " is ", " are ", " likes ", " loves ", "prefers", "name is", "called")):
            continue
        for pat in FACT_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            gd = m.groupdict()
            remembered = "subject" not in gd or not gd.get("subject")
            subject = gd.get("subject") or "companion_memory"
            predicate = normalize_predicate(gd.get("predicate"), remembered=remembered)
            obj = (gd.get("object") or "").strip(" .")
            if len(obj) < 3:
                continue
            memory_class = infer_memory_class(subject, predicate, obj, line, remembered=remembered)
            durability = infer_fact_durability(memory_class, predicate, line)
            retrieval_cues = make_keywords(f"{subject} {predicate} {obj} {line}")
            fact_id = "fact_" + stable_id(subject.lower(), predicate, obj.lower(), length=24)
            cand = {
                "id": fact_id,
                "subject": one_line(subject, 80),
                "predicate": predicate,
                "object": one_line(obj, 260),
                "confidence": 0.9 if any(k in low for k in ("remember", "canon", "important", "always", "never")) else 0.78,
                "summary": f"{one_line(subject, 80)} {predicate.replace('_', ' ')} {one_line(obj, 160)}",
                "text": line,
                "source_ids": [source_id] if source_id else [],
                "source_turn_ids": [source_id] if source_id else [],
                "speaker": speaker,
                "source_lane": source_lane,
                "memory_class": memory_class,
                "durability": durability,
                "evidence_quote": line,
                "retrieval_cues": retrieval_cues,
                "tags": ["auto_promoted", memory_class, f"predicate:{predicate}"],
                "status": "active",
            }
            cand["contextual_text"] = fact_contextual_text(cand)
            if reject_fact_candidate_reason(cand):
                continue
            candidates.append(cand)
            break
    return candidates


def upsert_semantic_fact(con: sqlite3.Connection, fact: dict[str, Any]) -> str:
    now = now_iso()
    subject, predicate, obj = canonical_fact_parts(fact)
    if not obj:
        return ""
    fact_id = str(fact.get("id") or "fact_" + stable_id(subject.lower(), predicate, obj.lower()))
    entity_id = "ent_" + stable_id(subject.lower(), length=20)
    summary = one_line(str(fact.get("summary") or f"{subject} {predicate.replace('_', ' ')} {obj}"), 420)
    text = str(fact.get("text") or summary)
    source_ids: list[str] = []
    for key in ("source_ids", "source_turn_ids"):
        value = fact.get(key) or []
        if isinstance(value, str):
            value = [value]
        for item in value:
            item_s = str(item)
            if item_s and item_s not in source_ids:
                source_ids.append(item_s)
    tags = normalize_fact_tags(fact)
    contextual_text = str(fact.get("contextual_text") or fact_contextual_text({**fact, "tags": tags}))
    con.execute(
        """
        INSERT INTO semantic_entities(id, canonical_name, entity_type, aliases_json, privacy_level, notes, created_at, updated_at)
        VALUES(?, ?, ?, '[]', ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name, updated_at=excluded.updated_at
        """,
        (entity_id, subject, fact.get("subject_type") or "unknown", fact.get("privacy_level"), fact.get("notes"), now, now),
    )
    mirror = {
        "id": "semantic_" + fact_id,
        "type": "semantic_fact",
        "timestamp": fact.get("event_time") or now,
        "timestamp_iso": fact.get("event_time") or now,
        "summary": summary,
        "text": f"Semantic fact: {summary}\nEvidence: {text}",
        "importance": 8,
        "source": {
            "path": "afterglow.semantic_facts",
            "section": fact_id,
            "kind": "semantic_fact",
            "source_ids": source_ids,
            "memory_class": fact.get("memory_class"),
            "durability": fact.get("durability"),
            "speaker": fact.get("speaker"),
            "source_lane": fact.get("source_lane"),
        },
    }
    upsert_memory(con, mirror)
    con.execute(
        """
        INSERT INTO semantic_facts(
            id, subject_entity_id, subject, predicate, object, object_entity_id, object_type,
            status, confidence, privacy_level, privacy_labels_json, event_time, valid_from,
            valid_to, summary, text, contextual_text, source_ids_json, tags_json,
            supersedes_fact_id, contradicted_by_fact_id, memory_id, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            subject=excluded.subject, predicate=excluded.predicate, object=excluded.object,
            status=excluded.status, confidence=excluded.confidence, summary=excluded.summary,
            text=excluded.text, contextual_text=excluded.contextual_text,
            source_ids_json=excluded.source_ids_json, tags_json=excluded.tags_json,
            memory_id=excluded.memory_id, updated_at=excluded.updated_at
        """,
        (
            fact_id, entity_id, subject, predicate, obj, fact.get("object_type"),
            fact.get("status") or "active", float(fact.get("confidence") or 0.75),
            fact.get("privacy_level"), json.dumps(fact.get("privacy_labels") or [], ensure_ascii=False),
            fact.get("event_time"), fact.get("valid_from"), fact.get("valid_to"),
            summary, text, contextual_text,
            json.dumps(source_ids, ensure_ascii=False),
            json.dumps(tags, ensure_ascii=False),
            fact.get("supersedes_fact_id"), fact.get("contradicted_by_fact_id"),
            mirror["id"], now, now,
        ),
    )
    con.execute("DELETE FROM semantic_facts_fts WHERE id=?", (fact_id,))
    con.execute(
        "INSERT INTO semantic_facts_fts(id, subject, predicate, object, summary, text, contextual_text, tags) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (fact_id, subject, predicate, obj, summary, text, contextual_text, " ".join(map(str, tags))),
    )
    return fact_id


def promote_fact_candidate(con: sqlite3.Connection, cand: dict[str, Any], audit_source: str = "promotion") -> tuple[str, str]:
    reason = reject_fact_candidate_reason(cand)
    if reason:
        record_fact_promotion_audit("rejected", f"{audit_source}:{reason}", cand)
        return "", "rejected"
    if float(cand.get("confidence") or 0) < 0.78:
        record_fact_promotion_audit("rejected", f"{audit_source}:low_confidence", cand)
        return "", "rejected"
    existing_id = existing_active_fact_id(con, cand)
    if existing_id:
        record_fact_promotion_audit("skip_existing", audit_source, cand, existing_id)
        return existing_id, "skip_existing"
    fact_id = upsert_semantic_fact(con, cand)
    if fact_id:
        record_fact_promotion_audit("promoted", audit_source, cand, fact_id)
        return fact_id, "promoted"
    record_fact_promotion_audit("rejected", f"{audit_source}:empty_fact", cand)
    return "", "rejected"


def promote_semantic_facts(con: sqlite3.Connection, limit: int = 2000) -> dict[str, int]:
    rows = con.execute(
        "SELECT id, summary, text FROM memories WHERE type != 'semantic_fact' ORDER BY timestamp_iso DESC LIMIT ?",
        (limit,),
    ).fetchall()
    seen = 0
    promoted = 0
    skipped_existing = 0
    rejected = 0
    for row in rows:
        for cand in extract_fact_candidates(f"{row['summary']}\n{row['text']}", source_id=row["id"]):
            seen += 1
            _, action = promote_fact_candidate(con, cand, audit_source="batch")
            if action == "promoted":
                promoted += 1
            elif action == "skip_existing":
                skipped_existing += 1
            else:
                rejected += 1
    return {
        "candidates_seen": seen,
        "facts_upserted": promoted,
        "skipped_existing": skipped_existing,
        "rejected": rejected,
    }


def fts_query(query: str) -> str:
    toks = tokens_for(query, limit=8)
    if not toks:
        return '"memory"'
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in toks)


def term_hits(tokens: list[str], text: str) -> int:
    low = (text or "").lower()
    return sum(1 for t in tokens if t in low)


def memory_time_label(value: Any) -> str:
    parsed = parse_time(value)
    if not parsed:
        return str(value or "unknown")
    local = parsed.astimezone(LOCAL_TZ)
    age_s = max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    if age_s < 90:
        age = "just now"
    elif age_s < 3600:
        age = f"{age_s // 60}m ago"
    elif age_s < 86400:
        age = f"{age_s // 3600}h ago"
    else:
        age = f"{age_s // 86400}d ago"
    return f"{age} | {local.strftime('%Y-%m-%d %I:%M %p')}"


def record_recall(con: sqlite3.Connection, results: list[dict[str, Any]], lane: str) -> None:
    now = now_iso()
    for item in results:
        mid = str(item.get("id") or "")
        if not mid:
            continue
        score = float(item.get("score") or 0.0)
        row = con.execute("SELECT first_recalled_at, recall_count FROM memory_recall_stats WHERE memory_id=?", (mid,)).fetchone()
        first = row["first_recalled_at"] if row else now
        count = int(row["recall_count"] or 0) + 1 if row else 1
        con.execute(
            """
            INSERT INTO memory_recall_stats(memory_id, first_recalled_at, last_recalled_at, recall_count, total_score, last_score, last_lane, reinforcement, decay_score, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
              last_recalled_at=excluded.last_recalled_at,
              recall_count=excluded.recall_count,
              total_score=memory_recall_stats.total_score + excluded.last_score,
              last_score=excluded.last_score,
              last_lane=excluded.last_lane,
              reinforcement=excluded.reinforcement,
              updated_at=excluded.updated_at
            """,
            (mid, first, now, count, score, score, lane, min(3.0, count * 0.15), now),
        )


def semantic_recall(query: str, limit: int = 6) -> list[dict[str, Any]]:
    tokens = tokens_for(query, limit=10)
    match = fts_query(query)
    results: list[dict[str, Any]] = []
    with connect() as con:
        con.row_factory = sqlite3.Row
        rows: list[sqlite3.Row] = []
        try:
            rows = con.execute(
                """
                SELECT m.*, bm25(memories_fts) AS rank, COALESCE(e.salience, 0) AS salience
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.id
                LEFT JOIN memory_emotion_profiles e ON e.memory_id = m.id
                WHERE memories_fts MATCH ?
                ORDER BY rank ASC, m.timestamp_iso DESC
                LIMIT ?
                """,
                (match, max(limit * 8, 30)),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query[:80]}%"
            rows = con.execute("SELECT *, 0 AS rank, 0 AS salience FROM memories WHERE text LIKE ? OR summary LIKE ? ORDER BY timestamp_iso DESC LIMIT ?", (like, like, max(limit * 8, 30))).fetchall()
        fact_rows = []
        try:
            fact_rows = con.execute(
                """
                SELECT sf.memory_id AS id, sf.id AS fact_id, sf.summary, sf.text, sf.updated_at AS timestamp_iso,
                       sf.confidence AS importance, bm25(semantic_facts_fts) AS rank
                FROM semantic_facts_fts
                JOIN semantic_facts sf ON sf.id = semantic_facts_fts.id
                WHERE semantic_facts_fts MATCH ? AND sf.status='active'
                ORDER BY rank ASC, sf.updated_at DESC
                LIMIT ?
                """,
                (match, max(8, limit * 3)),
            ).fetchall()
        except sqlite3.OperationalError:
            fact_rows = []
        for row in rows:
            text = f"{row['summary'] or ''}\n{row['text'] or ''}"
            hits = term_hits(tokens, text)
            try:
                rank_score = max(0.0, min(20.0, -float(row["rank"] or 0) * 4 if float(row["rank"] or 0) < 0 else 1.0))
            except Exception:
                rank_score = 1.0
            score = rank_score + hits * 5 + float(row["importance"] or 5) * 0.4 + float(row["salience"] or 0) * 4
            if query.lower() in text.lower():
                score += 30
            results.append({
                "id": row["id"],
                "type": row["type"],
                "timestamp": row["timestamp"],
                "timestamp_iso": row["timestamp_iso"],
                "score": round(score, 3),
                "summary": row["summary"],
                "text": row["text"],
                "source_kind": row["source_kind"],
                "source_path": row["source_path"],
                "evidence": "semantic_fact" if row["type"] == "semantic_fact" else "memory",
            })
        for row in fact_rows:
            text = f"{row['summary'] or ''}\n{row['text'] or ''}"
            score = 18 + term_hits(tokens, text) * 6 + float(row["importance"] or 0.75) * 5
            results.append({
                "id": row["id"],
                "fact_id": row["fact_id"],
                "type": "semantic_fact",
                "timestamp": row["timestamp_iso"],
                "timestamp_iso": row["timestamp_iso"],
                "score": round(score, 3),
                "summary": row["summary"],
                "text": row["text"],
                "source_kind": "semantic_fact",
                "source_path": "afterglow.semantic_facts",
                "evidence": "semantic_fact",
            })
        dedup: dict[str, dict[str, Any]] = {}
        for item in sorted(results, key=lambda r: float(r["score"]), reverse=True):
            key = str(item.get("id") or item.get("fact_id"))
            if key not in dedup:
                dedup[key] = item
        final = list(dedup.values())[:limit]
        record_recall(con, final, "deep_semantic")
        con.commit()
    return final


def format_recall(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f'No memories found for: {query}'
    lines = [f'=== Afterglow deep recall: "{query}" ({len(results)} result(s)) ===']
    for item in results:
        lines.append(
            f"- [{float(item.get('score') or 0):.1f}] evidence={item.get('evidence')} "
            f"when={memory_time_label(item.get('timestamp_iso') or item.get('timestamp'))} "
            f"type={item.get('type')} id={item.get('id')}: {one_line(item.get('summary') or item.get('text'), 420)}"
        )
    return "\n".join(lines)


def expand_memory_context(memory_id: str, window: int = 4) -> dict[str, Any]:
    with connect() as con:
        row = con.execute("SELECT * FROM memories WHERE id=? OR fingerprint=?", (memory_id, memory_id)).fetchone()
        if not row:
            return {"error": "memory not found", "memory_id": memory_id}
        source_path = row["source_path"]
        timestamp = row["timestamp_iso"]
        before = con.execute(
            "SELECT id, role, timestamp_iso, summary, text FROM (SELECT id, json_extract(entry_json, '$.source.role') AS role, timestamp_iso, summary, text FROM memories WHERE source_path=? AND timestamp_iso <= ? ORDER BY timestamp_iso DESC LIMIT ?) ORDER BY timestamp_iso ASC",
            (source_path, timestamp, window + 1),
        ).fetchall()
        after = con.execute(
            "SELECT id, json_extract(entry_json, '$.source.role') AS role, timestamp_iso, summary, text FROM memories WHERE source_path=? AND timestamp_iso > ? ORDER BY timestamp_iso ASC LIMIT ?",
            (source_path, timestamp, window),
        ).fetchall()
        return {
            "memory": dict(row),
            "neighbors": [dict(r) for r in before + after],
        }


def build_response_context(topics: list[str], limit: int = 5) -> dict[str, Any]:
    query = " ".join(topics).strip() or "general"
    memories = semantic_recall(query, limit=limit)
    payload = {
        "last_updated": now_iso(),
        "topics": topics,
        "query": query,
        "memories": [
            {
                "id": m.get("id"),
                "type": m.get("type"),
                "score": m.get("score"),
                "timestamp": m.get("timestamp_iso") or m.get("timestamp"),
                "text": one_line(m.get("summary") or m.get("text"), 320),
                "evidence": m.get("evidence"),
            }
            for m in memories
        ],
        "pipeline": "afterglow",
    }
    save_json(RESPONSE_CONTEXT, payload)
    return payload


def rebuild_hot_recall(limit: int = 10) -> dict[str, Any]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, type, timestamp_iso, importance, summary FROM memories ORDER BY importance DESC, timestamp_iso DESC LIMIT ?",
            (limit,),
        ).fetchall()
    payload = {
        "last_updated": now_iso(),
        "insights": [dict(r) for r in rows],
        "count": len(rows),
        "pipeline": "afterglow",
    }
    save_json(CURRENT_RECALL, payload)
    return payload


def summary() -> dict[str, Any]:
    with connect() as con:
        tables = {}
        for table in ("memories", "semantic_facts", "semantic_entities", "memory_recall_stats", "import_sources"):
            tables[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        by_type = {r["type"]: r["n"] for r in con.execute("SELECT type, COUNT(*) AS n FROM memories GROUP BY type ORDER BY n DESC")}
        newest = con.execute("SELECT MAX(timestamp_iso) FROM memories").fetchone()[0]
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
    return {
        "db": str(DB_PATH),
        "workspace": str(WORKSPACE),
        "sessions_dir": str(SESSIONS_DIR),
        "tables": tables,
        "memory_types": by_type,
        "newest_memory": newest,
        "quick_check": quick,
    }


def cmd_import_local(args: argparse.Namespace) -> None:
    with connect() as con:
        stats = import_local(con, include_sessions=not args.no_sessions, max_session_files=args.max_session_files)
        facts = promote_semantic_facts(con, limit=args.fact_limit) if args.promote_facts else {"candidates_seen": 0, "facts_upserted": 0}
        con.commit()
    report = {"imported_at": now_iso(), **stats, "semantic_fact_promotion": facts, "summary": summary()}
    save_json(IMPORT_REPORT, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def cmd_import_hindsight(args: argparse.Namespace) -> None:
    with connect() as con:
        stats = import_hindsight_export(con, Path(args.path))
        facts = promote_semantic_facts(con, limit=args.fact_limit) if args.promote_facts else {"candidates_seen": 0, "facts_upserted": 0}
        con.commit()
    print(json.dumps({"imported_at": now_iso(), **stats, "semantic_fact_promotion": facts, "summary": summary()}, indent=2, ensure_ascii=False))


def cmd_ingest_message(args: argparse.Namespace) -> None:
    text = args.text or sys.stdin.read()
    if not text.strip():
        return
    INBOUND_MESSAGE.parent.mkdir(parents=True, exist_ok=True)
    INBOUND_MESSAGE.write_text(text[:4000], encoding="utf-8")
    role = args.role or "user"
    speaker = "Assistant" if role == "assistant" else "User"
    with connect() as con:
        added = upsert_memory(con, {
            "type": "conversation",
            "timestamp": now_iso(),
            "timestamp_iso": now_iso(),
            "summary": f"{speaker}: {one_line(text, 220)}",
            "text": f"{speaker}: {text}",
            "importance": infer_importance(text, "conversation"),
            "source": {
                "path": args.source or "openclaw.message_received",
                "section": args.section or stable_id(now_iso(), text[:100], length=12),
                "kind": "openclaw_live",
                "role": role,
            },
        })
        fact_stats = {"candidates_seen": 0, "facts_upserted": 0, "skipped_existing": 0, "rejected": 0}
        for cand in extract_fact_candidates(text, source_id=args.source or ""):
            fact_stats["candidates_seen"] += 1
            _, action = promote_fact_candidate(con, cand, audit_source="live_ingest")
            if action == "promoted":
                fact_stats["facts_upserted"] += 1
            elif action == "skip_existing":
                fact_stats["skipped_existing"] += 1
            else:
                fact_stats["rejected"] += 1
        topics = extract_topics_from_lines([text])
        con.commit()
    build_response_context(topics, limit=5)
    print(json.dumps({"added": added, "topics": topics, "semantic_fact_promotion": fact_stats}, ensure_ascii=False))


def cmd_ingest_sessions(args: argparse.Namespace) -> None:
    with connect() as con:
        session_files = iter_session_files()
        if args.max_files:
            session_files = session_files[-args.max_files:]
        added = 0
        for path in session_files:
            added += import_session_file(con, path)
        if args.promote_facts:
            facts = promote_semantic_facts(con, limit=args.fact_limit)
        else:
            facts = {"candidates_seen": 0, "facts_upserted": 0}
        con.commit()
    print(json.dumps({"session_files": len(session_files), "entries_added": added, "semantic_fact_promotion": facts}, indent=2, ensure_ascii=False))


def cmd_promote_facts(args: argparse.Namespace) -> None:
    with connect() as con:
        stats = promote_semantic_facts(con, limit=args.limit)
        con.commit()
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Afterglow local memory core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-local")
    p.add_argument("--no-sessions", action="store_true")
    p.add_argument("--max-session-files", type=int)
    p.add_argument("--promote-facts", action="store_true")
    p.add_argument("--fact-limit", type=int, default=3000)
    p.set_defaults(func=cmd_import_local)

    p = sub.add_parser("import-hindsight")
    p.add_argument("path")
    p.add_argument("--promote-facts", action="store_true")
    p.add_argument("--fact-limit", type=int, default=3000)
    p.set_defaults(func=cmd_import_hindsight)

    p = sub.add_parser("ingest-message")
    p.add_argument("text", nargs="?")
    p.add_argument("--role", default="user")
    p.add_argument("--source", default="")
    p.add_argument("--section", default="")
    p.set_defaults(func=cmd_ingest_message)

    p = sub.add_parser("ingest-sessions")
    p.add_argument("--max-files", type=int, default=20)
    p.add_argument("--promote-facts", action="store_true")
    p.add_argument("--fact-limit", type=int, default=2000)
    p.set_defaults(func=cmd_ingest_sessions)

    p = sub.add_parser("recall")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=6)
    p.set_defaults(func=lambda a: print(format_recall(a.query, semantic_recall(a.query, limit=a.limit))))

    p = sub.add_parser("expand")
    p.add_argument("memory_id")
    p.add_argument("--window", type=int, default=4)
    p.set_defaults(func=lambda a: print(json.dumps(expand_memory_context(a.memory_id, a.window), indent=2, ensure_ascii=False)))

    p = sub.add_parser("context")
    p.add_argument("topics", nargs="*")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=lambda a: print(json.dumps(build_response_context(a.topics or ["general"], a.limit), indent=2, ensure_ascii=False)))

    p = sub.add_parser("promote-facts")
    p.add_argument("--limit", type=int, default=3000)
    p.set_defaults(func=cmd_promote_facts)

    p = sub.add_parser("rebuild-hot")
    p.set_defaults(func=lambda a: print(json.dumps(rebuild_hot_recall(), indent=2, ensure_ascii=False)))

    p = sub.add_parser("summary")
    p.set_defaults(func=lambda a: print(json.dumps(summary(), indent=2, ensure_ascii=False)))

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
