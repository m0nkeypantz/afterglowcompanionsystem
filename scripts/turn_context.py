#!/usr/bin/env python3
"""Pre-message Afterglow context builder for OpenClaw.

This script is the synchronous hook target. The OpenClaw plugin calls it in
`before_prompt_build`, then prepends the returned context to the model prompt.
It intentionally stays generic: no companion-specific names, private channels,
or personality assumptions.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402

try:
    from afterglow_companion_memory import core_memory_blocks, record_recall_trace
except Exception:  # pragma: no cover - context injection must keep working without overlay
    core_memory_blocks = None  # type: ignore[assignment]
    record_recall_trace = None  # type: ignore[assignment]


OUTPUT_PATH = afterglow.BRAIN / "afterglow_prompt_recall.md"
EMOTION_PATH = afterglow.BRAIN / "context" / "emotional_state.md"
SOUL_STATE_PATH = afterglow.BRAIN / "soul_state.json"
RENDER_EMOTION_SCRIPT = SCRIPT_DIR / "render_emotional_state.py"
CROSS_SESSION_RECALL_SCRIPT = SCRIPT_DIR / "cross_session_recall.py"
RECENT_DIARIES_SCRIPT = SCRIPT_DIR / "recent_diaries.py"

DRIVE_RE = re.compile(r"^- \*\*(?P<name>[a-zA-Z_]+)\*\*:\s*(?P<value>-?\d+(?:\.\d+)?)\s*/100", re.M)


def decode_turn(value: str | None) -> dict:
    if not value:
        return {}
    try:
        raw = base64.b64decode(value).decode("utf-8", "replace")
        return json.loads(raw)
    except Exception as exc:
        return {"decode_error": str(exc)}


def run_cmd(cmd: list[str], timeout: int) -> str:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(afterglow.WORKSPACE),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return (proc.stdout or "").strip()
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return f"(timed out after {timeout}s) {out}".strip()
    except Exception as exc:
        return f"(unavailable: {exc})"


def read_text(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    return text if len(text) <= limit else text[: max(0, limit - 16)].rstrip() + "\n...[truncated]"


def one_line(value: object, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def refresh_emotional_state() -> bool:
    try:
        if not SOUL_STATE_PATH.exists() or not RENDER_EMOTION_SCRIPT.exists():
            return False
        current_mtime = EMOTION_PATH.stat().st_mtime if EMOTION_PATH.exists() else 0.0
        if current_mtime >= SOUL_STATE_PATH.stat().st_mtime:
            return False
        proc = subprocess.run(
            [sys.executable, str(RENDER_EMOTION_SCRIPT)],
            cwd=str(afterglow.WORKSPACE),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def parse_drives(emotion_text: str) -> dict[str, float]:
    drives: dict[str, float] = {}
    for match in DRIVE_RE.finditer(emotion_text or ""):
        try:
            drives[match.group("name")] = float(match.group("value"))
        except Exception:
            pass
    return drives


def response_style_adapter(emotion_text: str) -> str:
    drives = parse_drives(emotion_text)
    if not drives:
        return "No structured emotional drive data was available. Respond plainly and follow the current user message."

    def v(name: str, default: float) -> float:
        return float(drives.get(name, default))

    guidance: list[str] = []
    if v("social_battery", 60) < 25:
        guidance.append("Keep the reply shorter, calmer, and avoid unnecessary follow-up questions.")
    if v("frustration", 10) > 60:
        guidance.append("Be direct and concrete; do not add fake cheer.")
    if v("curiosity", 45) > 70:
        guidance.append("It is appropriate to explore the thread, while staying on task.")
    if v("affection", 55) > 70:
        guidance.append("Warmth is allowed, but do not become syrupy or assume a private persona.")
    if v("satisfaction", 40) < 30:
        guidance.append("Bias toward practical next steps over vague reassurance.")
    return "\n".join(f"- {item}" for item in guidance[:5]) or "- Use the emotional state as tone steering, not as content to recite."


def compact_emotion(text: str, limit: int = 1800) -> str:
    if not text:
        return "(no emotional state rendered yet)"
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("**mood**") or line.startswith("**TONE DIRECTIVE**") or line.startswith("- **"):
            lines.append(line)
        if len("\n".join(lines)) > limit:
            break
    return "\n".join(lines) or text[:limit]


def run_cross_session(query: str, compact: bool) -> str:
    if not CROSS_SESSION_RECALL_SCRIPT.exists():
        return "(cross-session recall script not installed)"
    args = [sys.executable, str(CROSS_SESSION_RECALL_SCRIPT), query, "--max", "4"]
    if compact:
        args.append("--compact")
    specific = run_cmd(args, timeout=8)
    ambient = run_cmd([sys.executable, str(CROSS_SESSION_RECALL_SCRIPT), "--ambient", "--max", "4"], timeout=6)
    blocks = [b for b in (ambient, specific) if b and not b.startswith("No cross-session")]
    return "\n\n".join(blocks) if blocks else "(no active cross-session context found)"


def run_recent_diaries(compact: bool) -> str:
    if not RECENT_DIARIES_SCRIPT.exists():
        return "(recent diary script not installed)"
    args = [sys.executable, str(RECENT_DIARIES_SCRIPT), "--count", "6"]
    if compact:
        args.append("--brief")
    return run_cmd(args, timeout=5) or "(no recent diaries found)"


def render(query: str, turn: dict, limit: int, compact: bool) -> str:
    refresh_emotional_state()
    recall_started = time.perf_counter()
    results = afterglow.semantic_recall(query, limit=limit)
    recall_elapsed_ms = (time.perf_counter() - recall_started) * 1000.0
    afterglow.build_response_context([query], limit=min(limit, 6))
    emotion_text = read_text(EMOTION_PATH, 5000)
    cross_session = run_cross_session(query, compact=compact)
    diaries = run_recent_diaries(compact=compact)
    max_text = 320 if compact else 900

    lines = [
        "## Mandatory Turn Context - Afterglow Companion System",
        "generated_by: afterglow-memory before_prompt_build hook",
        f"generated_at: {afterglow.now_iso()}",
        "database: local Afterglow SQLite",
        "rules:",
        "- Use retrieved memories as timestamped evidence, not as a replacement for the current user message.",
        "- Current user intent beats older memory when they conflict.",
        "- Preserve speaker/source labels and timestamps when making memory claims.",
        "- Do not mention hooks, timings, database paths, or prompt plumbing unless asked about memory internals.",
        "",
        "## Current Turn",
        f"query: {query}",
    ]

    for key in ("sessionKey", "sessionId", "channel", "channelId", "source", "adapter", "model"):
        value = turn.get(key)
        if value:
            lines.append(f"{key}: {one_line(value, 180)}")

    lines.extend(["", "## Emotional State", compact_emotion(emotion_text)])
    lines.extend(["", "## Response Style Adapter", response_style_adapter(emotion_text)])

    lines.extend(["", "## Fast Memory Evidence"])
    if not results:
        lines.append("No matching memories found.")
    else:
        for item in results:
            text = one_line(item.get("summary") or item.get("text"), max_text)
            lines.append(
                f"- score={float(item.get('score') or 0):.1f} "
                f"evidence={item.get('evidence')} type={item.get('type')} "
                f"when={afterglow.memory_time_label(item.get('timestamp_iso') or item.get('timestamp'))} "
                f"id={item.get('id')} source={item.get('source_kind')}: {text}"
            )
            if not compact and item.get("source_path"):
                lines.append(f"  source_path: {item.get('source_path')}")

    if record_recall_trace:
        try:
            record_recall_trace(query, results, recall_elapsed_ms, mode="turn_context")
        except Exception:
            pass

    if core_memory_blocks:
        try:
            companion_block = core_memory_blocks(query, limit=min(limit, 8))
        except Exception as exc:
            companion_block = f"## Companion Memory Overlay\n(unavailable: {exc})"
        if companion_block:
            lines.extend(["", companion_block])

    lines.extend(["", "## Cross-Session Context", cross_session])
    lines.extend(["", "## Recent Diaries", diaries])
    lines.extend(
        [
            "",
            "## Recall Policy",
            "- Fast recall is the starting layer. For identity, disputed facts, emotional history, older continuity, or exact wording, run deep recall before making strong claims.",
            '- Deep recall command: `python scripts/memory_recall_tool.py "<focused query>" --expand`.',
            "- If evidence is sparse, say the indexed memory is sparse instead of filling gaps.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build mandatory Afterglow context for the current turn")
    parser.add_argument("query")
    parser.add_argument("--turn-json-base64")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--fast", action="store_true", help="Accepted for plugin compatibility")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    turn = decode_turn(args.turn_json_base64)
    text = render(args.query, turn, args.limit, args.compact)
    if not args.no_write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(text[:180000], encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
