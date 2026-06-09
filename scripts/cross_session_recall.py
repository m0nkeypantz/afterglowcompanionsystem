#!/usr/bin/env python3
"""Recall relevant recent activity from other OpenClaw sessions."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE") or Path(__file__).resolve().parents[1]).resolve()
DIGEST_FILE = WORKSPACE / "brain" / "current_cross_session.json"
DIGEST_SCRIPT = Path(__file__).resolve().parent / "cross_session_digest.py"
REFRESH_STALE_SECONDS = float(os.environ.get("AFTERGLOW_CROSS_SESSION_REFRESH_STALE_SECONDS", "20"))
REFRESH_TIMEOUT_SECONDS = float(os.environ.get("AFTERGLOW_CROSS_SESSION_REFRESH_TIMEOUT_SECONDS", "5"))

STOP = {
    "the", "and", "that", "with", "from", "this", "your", "have", "what", "when",
    "just", "like", "about", "there", "would", "could", "should", "were", "been",
    "into", "because", "while", "yeah", "okay", "good", "want", "think", "know",
    "going", "really", "actually", "something", "everything", "anything", "here",
    "will", "make", "take", "being", "does", "done", "working", "looking", "getting",
    "trying", "thing", "things", "need", "check", "look", "message", "messages",
    "session", "sessions", "user", "assistant",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def one_line(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 3)].rstrip() + "..."


def digest_age_seconds() -> float | None:
    try:
        return max(0.0, time.time() - DIGEST_FILE.stat().st_mtime)
    except OSError:
        return None


def refresh_digest_if_stale() -> None:
    if os.environ.get("AFTERGLOW_CROSS_SESSION_REFRESH", "1").lower() in {"0", "false", "no"}:
        return
    age = digest_age_seconds()
    if age is not None and age < REFRESH_STALE_SECONDS:
        return
    if not DIGEST_SCRIPT.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(DIGEST_SCRIPT)],
            cwd=str(WORKSPACE),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=REFRESH_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        pass


def tokens_for(query: str) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"[a-zA-Z0-9_@#.'-]{3,}", (query or "").lower()):
        token = raw.strip(".-'_")
        if len(token) < 3 or token in STOP:
            continue
        if token not in out:
            out.append(token)
    return out[:12]


def session_text(session: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.extend(str(x) for x in (session.get("topics") or []))
    parts.append(str(session.get("summary") or ""))
    parts.append(str(session.get("last_user_message") or ""))
    parts.append(str(session.get("last_assistant_message") or ""))
    for item in session.get("recent_messages") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


def score_session(session: dict[str, Any], tokens: list[str]) -> float:
    text = session_text(session).lower()
    score = 0.0
    for token in tokens:
        if token in text:
            score += 4.0
    try:
        modified = str(session.get("modified_at") or "")
        # ISO lexical recency is good enough for tie-breaking here.
        if modified:
            score += 1.0
    except Exception:
        pass
    if session.get("emotional_signals"):
        score += 0.5
    return score


def recall(query: str, max_items: int, ambient: bool) -> list[dict[str, Any]]:
    refresh_digest_if_stale()
    digest = load_json(DIGEST_FILE, {})
    sessions = digest.get("sessions") if isinstance(digest.get("sessions"), list) else []
    if ambient:
        return sessions[:max_items]
    tokens = tokens_for(query)
    if not tokens:
        return sessions[:max_items]
    scored = [(score_session(s, tokens), s) for s in sessions]
    return [s for score, s in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0][:max_items]


def render_session(session: dict[str, Any], compact: bool) -> list[str]:
    lines = [
        f"- session={session.get('session_key')} modified={session.get('modified_at')} messages={session.get('message_count')}",
        f"  summary: {one_line(str(session.get('summary') or ''), 360 if compact else 700)}",
    ]
    if session.get("topics"):
        lines.append(f"  topics: {', '.join(str(x) for x in session.get('topics', [])[:8])}")
    if session.get("emotional_signals"):
        labels = ", ".join(str(x.get("label")) for x in session["emotional_signals"] if isinstance(x, dict))
        if labels:
            lines.append(f"  emotional_signals: {labels}")
    recent = session.get("recent_messages") or []
    for msg in recent[-(3 if compact else 6) :]:
        if isinstance(msg, dict):
            lines.append(f"  {msg.get('role')}: {one_line(str(msg.get('text') or ''), 300 if compact else 650)}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall recent cross-session context")
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--max", type=int, default=4)
    parser.add_argument("--ambient", action="store_true")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = recall(args.query, args.max, args.ambient)
    if args.json:
        print(json.dumps({"query": args.query, "ambient": args.ambient, "sessions": rows}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("No cross-session context found.")
        return 0
    header = "## Cross-Session Ambient Context" if args.ambient else f'## Cross-Session Recall for "{args.query}"'
    print(header)
    for session in rows:
        print("\n".join(render_session(session, compact=args.compact)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
