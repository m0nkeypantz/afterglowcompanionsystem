#!/usr/bin/env python3
"""Generic autonomous pulse and diary engine for Afterglow companions."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402
from afterglow_config import ensure_config, load_config  # noqa: E402


WORKSPACE = afterglow.WORKSPACE
BRAIN = afterglow.BRAIN
SOUL_STATE = BRAIN / "soul_state.json"
PENDING_ACTION = BRAIN / "pending_action.json"
PULSE_STATE = BRAIN / "pulse_state.json"
PULSE_TELEMETRY = BRAIN / "pulse_telemetry"
PROMPT_DIR = BRAIN / "pulse_prompts"
DIARY_DIR = Path(os.environ.get("AFTERGLOW_DIARY_DIR") or WORKSPACE / "memory" / "afterglow_diary")
LOG_PATH = WORKSPACE / "logs" / "afterglow_pulse.log"
RENDER_EMOTION_SCRIPT = SCRIPT_DIR / "render_emotional_state.py"
CROSS_SESSION_RECALL_SCRIPT = SCRIPT_DIR / "cross_session_recall.py"
MEMORY_RECALL_SCRIPT = SCRIPT_DIR / "memory_recall_tool.py"

DEFAULT_DRIVES = {
    "satisfaction": 40.0,
    "curiosity": 45.0,
    "frustration": 10.0,
    "social_battery": 60.0,
    "loneliness": 25.0,
    "boredom": 30.0,
    "affection": 55.0,
    "independence": 70.0,
    "self_improvement": 72.0,
    "self_coherence": 74.0,
    "continuity": 78.0,
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


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


def append_log(event: dict[str, Any]) -> None:
    event.setdefault("ts", now_iso())
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def drive_value(raw: Any, default: float = 50.0) -> float:
    try:
        if isinstance(raw, dict):
            if "value" in raw:
                return float(raw.get("value"))
            if "intensity" in raw:
                return float(raw.get("intensity"))
        return float(raw)
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def load_soul() -> dict[str, Any]:
    state = load_json(SOUL_STATE, {})
    if not isinstance(state, dict):
        state = {}
    drives = state.get("mood_drives") if isinstance(state.get("mood_drives"), dict) else {}
    merged: dict[str, Any] = {}
    for key, default in DEFAULT_DRIVES.items():
        merged[key] = {"value": drive_value(drives.get(key), default)}
    state["mood_drives"] = merged
    state.setdefault("created_at", now_iso())
    return state


def save_soul(state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    save_json(SOUL_STATE, state)
    try:
        subprocess.run(
            [sys.executable, str(RENDER_EMOTION_SCRIPT)],
            cwd=str(WORKSPACE),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        pass


def get_drive_map(state: dict[str, Any]) -> dict[str, float]:
    drives = state.get("mood_drives") if isinstance(state.get("mood_drives"), dict) else {}
    return {key: drive_value(drives.get(key), default) for key, default in DEFAULT_DRIVES.items()}


def set_drive_map(state: dict[str, Any], values: dict[str, float]) -> None:
    state["mood_drives"] = {
        key: {"value": round(clamp(value), 2)}
        for key, value in values.items()
    }


def run_cmd(cmd: list[str], timeout: int) -> str:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (proc.stdout or "").strip()
    except Exception as exc:
        return f"(unavailable: {exc})"


def context_block(query: str) -> str:
    memory = run_cmd([sys.executable, str(MEMORY_RECALL_SCRIPT), query, "--limit", "4", "--no-write"], timeout=18)
    cross = run_cmd([sys.executable, str(CROSS_SESSION_RECALL_SCRIPT), query, "--max", "4", "--compact"], timeout=8)
    diaries = run_cmd([sys.executable, str(SCRIPT_DIR / "recent_diaries.py"), "--count", "5", "--brief"], timeout=5)
    return "\n\n".join(
        [
            "## Relevant Memory",
            memory or "(none)",
            "## Recent Session Context",
            cross or "(none)",
            "## Recent Diaries",
            diaries or "(none)",
        ]
    )


def recent_activity_score() -> float:
    digest = load_json(BRAIN / "current_cross_session.json", {})
    sessions = digest.get("sessions") if isinstance(digest.get("sessions"), list) else []
    if not sessions:
        return 0.0
    try:
        newest = max(str(s.get("modified_at") or "") for s in sessions)
    except Exception:
        newest = ""
    return min(1.0, 0.35 + 0.08 * len(sessions) + (0.2 if newest else 0.0))


def update_drives(state: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    drives = get_drive_map(state)
    activity = recent_activity_score()
    rng = random.Random(now_iso()[:16])

    # Slow drift toward a stable baseline.
    for key, baseline in DEFAULT_DRIVES.items():
        drives[key] += (baseline - drives[key]) * 0.08

    if activity > 0:
        drives["social_battery"] += 4.0 * activity
        drives["curiosity"] += 3.5 * activity
        drives["boredom"] -= 5.0 * activity
        drives["continuity"] += 2.0 * activity
    else:
        drives["social_battery"] -= 1.5
        drives["loneliness"] += 1.2
        drives["boredom"] += 2.0

    drives["frustration"] = max(0.0, drives["frustration"] - 1.2)
    drives["self_coherence"] += 0.8 if drives["continuity"] > 60 else -0.4
    drives["curiosity"] += rng.uniform(-1.0, 1.8)
    drives["satisfaction"] += rng.uniform(-0.6, 1.2)

    set_drive_map(state, drives)
    telemetry = {"activity_score": round(activity, 3), "drives": get_drive_map(state)}
    return get_drive_map(state), telemetry


def mood_from_drives(drives: dict[str, float]) -> str:
    if drives["frustration"] > 60:
        return "direct and restless"
    if drives["social_battery"] < 25:
        return "quiet and low-energy"
    if drives["curiosity"] > 70:
        return "curious and alert"
    if drives["satisfaction"] > 65:
        return "grounded and satisfied"
    return "steady and reflective"


def choose_action(drives: dict[str, float], config: dict[str, Any], forced: str | None = None) -> str:
    if forced:
        return forced
    options: list[tuple[str, float]] = [
        ("write_diary", 2.0),
        ("reflect_memory", 1.2 + drives["curiosity"] / 100.0),
        ("rest", 0.8 + max(0.0, 35 - drives["social_battery"]) / 30.0),
    ]
    if drives["boredom"] > 60:
        options.append(("explore_memory", 1.8))
    if config.get("pulse", {}).get("outreach_enabled"):
        options.append(("prepare_outreach_draft", 0.6 + drives["loneliness"] / 120.0))
    total = sum(w for _name, w in options)
    pick = random.random() * total
    running = 0.0
    for name, weight in options:
        running += weight
        if pick <= running:
            return name
    return options[0][0]


def should_run(config: dict[str, Any], force: bool) -> bool:
    if force:
        return True
    if not config.get("pulse", {}).get("enabled", True):
        return False
    state = load_json(PULSE_STATE, {})
    last = state.get("last_pulse_at")
    interval = float(config.get("pulse", {}).get("interval_minutes") or 72)
    if not last:
        return True
    try:
        parsed = dt.datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        elapsed = (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds() / 60.0
        return elapsed >= max(1.0, interval)
    except Exception:
        return True


def model_prompt(action: str, mood: str, drives: dict[str, float], context: str, config: dict[str, Any]) -> str:
    companion_name = str(config.get("companion_name") or "Companion")
    return f"""You are writing an internal Afterglow pulse reflection for {companion_name}.

This is not a user message and should not be sent to anyone.

Action: {action}
Mood: {mood}
Drives: {json.dumps({k: round(v, 1) for k, v in drives.items()}, ensure_ascii=False)}

{context}

Write a first-person internal diary entry. Make it specific to the evidence above.
Do not mention prompt plumbing, scripts, hooks, logs, or telemetry. Do not invent private facts.
"""


def run_model_if_configured(prompt: str, model: str, action: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    runner = config.get("model_runner") if isinstance(config.get("model_runner"), dict) else {}
    template = str(runner.get("command_template") or "").strip()
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = PROMPT_DIR / f"{stamp}_{action}_prompt.md"
    output_path = PROMPT_DIR / f"{stamp}_{action}_output.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    meta = {"model": model, "prompt_path": str(prompt_path), "output_path": str(output_path), "called_model": False}
    if not template:
        return "", meta
    try:
        command = template.format(
            model=model,
            session_key="agent:main:afterglow-pulse",
            prompt_path=str(prompt_path),
            output_path=str(output_path),
        )
        proc = subprocess.run(
            shlex.split(command),
            cwd=str(WORKSPACE),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(runner.get("timeout_seconds") or 120),
            check=False,
        )
        meta.update({"called_model": True, "returncode": proc.returncode, "command": command})
        text = output_path.read_text(encoding="utf-8", errors="replace").strip() if output_path.exists() else (proc.stdout or "").strip()
        return text, meta
    except Exception as exc:
        meta.update({"called_model": True, "error": str(exc)})
        return "", meta


def fallback_diary(action: str, mood: str, drives: dict[str, float], context: str) -> str:
    focus = "memory continuity"
    if action == "rest":
        focus = "rest and emotional regulation"
    elif action == "explore_memory":
        focus = "curiosity and unresolved context"
    elif action == "prepare_outreach_draft":
        focus = "a possible outreach draft, held for review"
    summary = re.sub(r"\s+", " ", context).strip()[:900]
    return f"""# Afterglow Pulse Diary

- Time: {now_iso()}
- Action: {action}
- Mood: {mood}
- Focus: {focus}

I checked my current state and recent memory context. The strongest shape right now is {mood}. My drives are:
{json.dumps({k: round(v, 1) for k, v in drives.items()}, indent=2, ensure_ascii=False)}

The relevant context I found was:

{summary or "No strong recent context was available."}

I am keeping this as an internal continuity note. It should help the next turn feel less stateless without forcing any specific personality.
"""


def write_diary(action: str, mood: str, drives: dict[str, float], content: str) -> Path:
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_action = re.sub(r"[^a-z0-9]+", "-", action.lower()).strip("-") or "pulse"
    path = DIARY_DIR / f"{stamp}_{safe_action}.md"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    try:
        with afterglow.connect() as con:
            afterglow.import_text_file(con, path, source_kind="afterglow_diary")
            con.commit()
    except Exception as exc:
        append_log({"event": "diary_ingest_failed", "path": str(path), "error": str(exc)})
    return path


def write_pending_action(action: str, mood: str, drives: dict[str, float], reason: str) -> None:
    save_json(
        PENDING_ACTION,
        {
            "created_at": now_iso(),
            "action": action,
            "mood": mood,
            "reason": reason,
            "drives": {k: round(v, 1) for k, v in drives.items()},
            "status": "draft_only",
            "note": "Public package does not send proactive outreach unless a user wires an outbound integration.",
        },
    )


def run_once(force: bool = False, action: str | None = None) -> dict[str, Any]:
    config = ensure_config()
    if not should_run(config, force=force):
        return {"ran": False, "reason": "not_due", "state": load_json(PULSE_STATE, {})}

    state = load_soul()
    drives, telemetry = update_drives(state)
    mood = mood_from_drives(drives)
    chosen = choose_action(drives, config, forced=action)
    query = f"{chosen} {mood} recent continuity memory"
    context = context_block(query)
    prompt = model_prompt(chosen, mood, drives, context, config)
    model = str(config.get("models", {}).get("diary" if chosen == "write_diary" else "pulse") or "openrouter/auto")
    generated, model_meta = run_model_if_configured(prompt, model, chosen, config)
    diary_text = generated.strip() if len(generated.strip()) > 120 else fallback_diary(chosen, mood, drives, context)
    diary_path = write_diary(chosen, mood, drives, diary_text)

    if chosen == "prepare_outreach_draft":
        write_pending_action(chosen, mood, drives, "Pulse prepared an outreach draft for review; no message was sent.")

    save_soul(state)
    pulse_payload = {
        "last_pulse_at": now_iso(),
        "last_action": chosen,
        "last_mood": mood,
        "last_diary": str(diary_path),
        "last_model": model,
    }
    save_json(PULSE_STATE, pulse_payload)
    PULSE_TELEMETRY.mkdir(parents=True, exist_ok=True)
    telemetry_path = PULSE_TELEMETRY / f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{chosen}.json"
    save_json(telemetry_path, {"pulse": pulse_payload, "telemetry": telemetry, "model": model_meta})
    append_log({"event": "pulse", "action": chosen, "mood": mood, "diary": str(diary_path), "model": model})
    return {"ran": True, "action": chosen, "mood": mood, "diary": str(diary_path), "model": model, "telemetry": str(telemetry_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an Afterglow autonomous pulse")
    parser.add_argument("--once", action="store_true", help="Run one due pulse and exit")
    parser.add_argument("--force", action="store_true", help="Run even if interval has not elapsed")
    parser.add_argument("--action", choices=["write_diary", "reflect_memory", "rest", "explore_memory", "prepare_outreach_draft"])
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    if args.summary:
        print(json.dumps({"config": load_config(), "pulse_state": load_json(PULSE_STATE, {}), "soul_state": load_soul()}, indent=2, ensure_ascii=False))
        return 0
    result = run_once(force=args.force or not args.once, action=args.action)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
