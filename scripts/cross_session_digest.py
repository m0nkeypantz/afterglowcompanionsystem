#!/usr/bin/env python3
"""Build a compact digest of recent OpenClaw activity from other sessions."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE") or Path(__file__).resolve().parents[1]).resolve()
STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR") or WORKSPACE.parent).resolve()
SESSIONS_DIR = Path(os.environ.get("OPENCLAW_SESSIONS_DIR") or STATE_DIR / "agents" / "main" / "sessions").resolve()
DIGEST_FILE = WORKSPACE / "brain" / "current_cross_session.json"

SKIP_PATTERNS = [
    "heartbeat",
    "subagent",
    "cron:",
    "agent:main:cron:",
    "agent:main:pulse",
    "pulse",
    "autonomous",
    "index-diaries",
    "memory-import",
]

NOISE_MARKERS = [
    "[assistant turn failed before producing content]",
    "[Inter-session message]",
    "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>",
    "[Internal task completion event]",
    "sourceTool=subagent_announce",
]

EMOTION_KEYWORDS = {
    "care": ["love", "care", "thanks", "appreciate", "proud", "miss"],
    "frustration": ["frustrated", "annoying", "broken", "stuck", "failed", "bug", "crash"],
    "curiosity": ["why", "how", "what if", "wonder", "curious", "investigate"],
    "progress": ["done", "fixed", "verified", "works", "better", "finished"],
    "uncertainty": ["not sure", "unsure", "confused", "missed", "gap"],
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def one_line(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 3)].rstrip() + "..."


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def session_haystack(key: str, meta: dict[str, Any] | None = None) -> str:
    parts = [key]
    if isinstance(meta, dict):
        parts.append(str(meta.get("label") or ""))
        origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
        parts.extend(str(origin.get(k) or "") for k in ("label", "provider", "from", "to"))
    return " ".join(p for p in parts if p).lower()


def should_skip_session(key: str, meta: dict[str, Any] | None = None) -> bool:
    hay = session_haystack(key, meta)
    return any(pattern in hay for pattern in SKIP_PATTERNS)


def is_noise(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return True
    head = text[:1200]
    return any(marker in head for marker in NOISE_MARKERS)


def strip_transport(text: str) -> str:
    text = str(text or "")
    tag = re.search(r"<(?:user|human|companion_user|turn)_message>\s*(.*?)\s*</(?:user|human|companion_user|turn)_message>", text, re.S | re.I)
    if tag:
        text = tag.group(1)
    text = re.sub(r"<(?:bridge|system|transport)_system_context>[\s\S]*?</(?:bridge|system|transport)_system_context>\s*", "", text, flags=re.I)
    text = re.sub(r"Conversation info \(untrusted metadata\):\s*```json\s*\{.*?\}\s*```\s*", "", text, flags=re.S)
    text = re.sub(r"Sender \(untrusted metadata\):\s*```json\s*\{.*?\}\s*```\s*", "", text, flags=re.S)
    text = re.sub(r"<<<EXTERNAL_UNTRUSTED_CONTENT.*?<<<END_EXTERNAL_UNTRUSTED_CONTENT.*?>>>", "", text, flags=re.S)
    return text.strip()


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for item in content:
            if isinstance(item, dict):
                bits.append(str(item.get("text") or item.get("content") or ""))
        return " ".join(b for b in bits if b.strip())
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return ""


def read_session_index() -> dict[str, Any]:
    data = load_json(SESSIONS_DIR / "sessions.json", {})
    return data if isinstance(data, dict) else {}


def session_files(max_age_hours: float) -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - max_age_hours * 3600
    files = [
        path for path in SESSIONS_DIR.glob("*.jsonl")
        if path.is_file() and ".checkpoint." not in path.name and path.stat().st_mtime >= cutoff
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def read_recent_messages(path: Path, max_messages: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_messages * 6 :]
    except Exception:
        return messages
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = str(msg.get("role") or obj.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        text = strip_transport(content_text(msg.get("content") if "content" in msg else obj.get("content")))
        if is_noise(text):
            continue
        ts = obj.get("ts") or obj.get("timestamp") or msg.get("timestamp") or path.stat().st_mtime
        messages.append({"role": role, "text": one_line(text, 650), "timestamp": ts})
    return messages[-max_messages:]


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", (text or "").lower()))


def summarize(messages: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(m["text"] for m in messages)
    terms = tokenize(text)
    topics = [t for t in terms if len(t) > 4][:12]
    emotions: list[dict[str, Any]] = []
    low = text.lower()
    for label, words in EMOTION_KEYWORDS.items():
        matches = [w for w in words if w in low]
        if matches:
            emotions.append({"label": label, "matches": matches[:4]})
    last_user = next((m["text"] for m in reversed(messages) if m["role"] == "user"), "")
    last_assistant = next((m["text"] for m in reversed(messages) if m["role"] == "assistant"), "")
    return {
        "topics": topics[:10],
        "emotional_signals": emotions[:5],
        "last_user_message": one_line(last_user, 320),
        "last_assistant_message": one_line(last_assistant, 320),
        "summary": one_line(last_user or last_assistant or text, 420),
    }


def build_digest(max_age_hours: float, max_messages: int, max_sessions: int) -> dict[str, Any]:
    index = read_session_index()
    sessions: list[dict[str, Any]] = []
    for path in session_files(max_age_hours):
        key = path.stem
        meta = index.get(key) if isinstance(index.get(key), dict) else {}
        if should_skip_session(key, meta):
            continue
        messages = read_recent_messages(path, max_messages=max_messages)
        if not messages:
            continue
        summary = summarize(messages)
        sessions.append(
            {
                "session_key": key,
                "path": str(path),
                "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "message_count": len(messages),
                "recent_messages": messages,
                **summary,
            }
        )
        if len(sessions) >= max_sessions:
            break
    return {
        "generated_at": now_iso(),
        "sessions_dir": str(SESSIONS_DIR),
        "window_hours": max_age_hours,
        "sessions": sessions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Afterglow cross-session digest")
    parser.add_argument("--hours", type=float, default=18.0)
    parser.add_argument("--max-messages", type=int, default=24)
    parser.add_argument("--max-sessions", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_digest(args.hours, args.max_messages, args.max_sessions)
    save_json(DIGEST_FILE, payload)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote {DIGEST_FILE} with {len(payload['sessions'])} session(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
