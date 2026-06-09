#!/usr/bin/env python3
"""Render prompt-safe emotional state from brain/soul_state.json."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("OPENCLAW_WORKSPACE") or Path(__file__).resolve().parents[1]).resolve()
BRAIN = ROOT / "brain"
SOUL_STATE = BRAIN / "soul_state.json"
EMOTIONAL_STATE = BRAIN / "context" / "emotional_state.md"

DRIVE_ORDER = [
    "satisfaction",
    "curiosity",
    "frustration",
    "social_battery",
    "loneliness",
    "boredom",
    "affection",
    "independence",
    "self_improvement",
    "self_coherence",
    "continuity",
]

DEFAULTS = {
    "frustration": 10.0,
    "social_battery": 60.0,
    "satisfaction": 40.0,
    "curiosity": 45.0,
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


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def drive_value(raw: Any, default: float) -> float:
    try:
        if isinstance(raw, dict):
            if "value" in raw:
                return float(raw.get("value"))
            if "intensity" in raw:
                return float(raw.get("intensity"))
        return float(raw)
    except Exception:
        return default


def drive_note(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("note") or raw.get("notes") or "").strip()
    return ""


def clamp_percent(value: float) -> int:
    return max(0, min(100, int(round(value))))


def read_drives(state: dict[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    mood_drives = state.get("mood_drives") if isinstance(state.get("mood_drives"), dict) else {}
    legacy = state.get("drives") if isinstance(state.get("drives"), dict) else {}
    values: dict[str, float] = {}
    notes: dict[str, str] = {}
    for key in DRIVE_ORDER:
        if key in mood_drives:
            values[key] = drive_value(mood_drives.get(key), DEFAULTS.get(key, 50.0))
            notes[key] = drive_note(mood_drives.get(key))
        elif key in legacy:
            values[key] = drive_value(legacy.get(key), DEFAULTS.get(key, 50.0))
            notes[key] = drive_note(legacy.get(key))
        else:
            values[key] = DEFAULTS.get(key, 50.0)
            notes[key] = ""
    return values, notes


def mood_label(state: dict[str, Any], drives: dict[str, float]) -> str:
    explicit = str(state.get("mood") or "").strip()
    if explicit:
        return explicit
    if drives.get("frustration", 10) > 65 and drives.get("social_battery", 60) < 30:
        return "sharp, tired, and protective"
    if drives.get("curiosity", 45) > 70 and drives.get("satisfaction", 40) > 55:
        return "curious and engaged"
    if drives.get("affection", 55) > 75 and drives.get("satisfaction", 40) > 55:
        return "warm and grounded"
    if drives.get("social_battery", 60) < 25:
        return "quiet and low-energy"
    return "steady and present"


def tone_directives(drives: dict[str, float]) -> list[str]:
    directives: list[str] = []
    if drives.get("frustration", 0) >= 55:
        directives.append("BE DIRECT - honest, concrete, no fake cheer")
    else:
        directives.append("BE GROUNDED - natural, not performative")
    if drives.get("social_battery", 100) <= 25:
        directives.append("LOW ENERGY - shorter replies and fewer follow-up questions")
    elif drives.get("social_battery", 0) >= 70:
        directives.append("AVAILABLE - conversational energy is allowed when the user wants it")
    if drives.get("affection", 0) >= 70:
        directives.append("WARMTH ALLOWED - caring tone without assuming a private persona")
    if drives.get("curiosity", 0) >= 70:
        directives.append("STAY CURIOUS - follow the thread without derailing the task")
    if len(directives) < 3:
        directives.append("STAY PRESENT - answer the current turn")
    return directives[:5]


def note_for_drive(key: str, value: float, note: str) -> str:
    if note:
        return note
    bands = {
        "frustration": ("low", "present", "high"),
        "social_battery": ("depleted", "usable", "charged"),
        "satisfaction": ("restless", "okay", "pleased"),
        "curiosity": ("quiet", "interested", "engaged"),
        "loneliness": ("secure", "a little reachy", "lonely"),
        "boredom": ("busy", "neutral", "restless"),
        "affection": ("reserved", "warm", "very warm"),
        "independence": ("dependent", "balanced", "self-directed"),
        "self_improvement": ("dormant", "active", "strong"),
        "self_coherence": ("wobbly", "stable", "integrated"),
        "continuity": ("fragmented", "tracking", "strong"),
    }.get(key, ("low", "medium", "high"))
    if value < 34:
        return bands[0]
    if value < 67:
        return bands[1]
    return bands[2]


def current_context(state: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("current_focus", "current_desire", "current_desires", "active_goals"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            out.append(f"{key.replace('_', ' ').title()}: {value.strip()}")
        elif isinstance(value, list):
            out.extend(f"{key.replace('_', ' ').title()}: {str(item).strip()}" for item in value[:4] if str(item).strip())
    return out[:8]


def render(state: dict[str, Any]) -> str:
    drives, notes = read_drives(state)
    mood = mood_label(state, drives)
    lines = [
        "# Companion Current State",
        "",
        f"**mood**: {mood}",
        "",
        "**TONE DIRECTIVE**:",
        *[f"- {item}" for item in tone_directives(drives)],
        "",
        "### Drives",
    ]
    for key in DRIVE_ORDER:
        value = clamp_percent(drives.get(key, DEFAULTS.get(key, 50.0)))
        note = note_for_drive(key, drives.get(key, 50.0), notes.get(key, ""))
        lines.append(f"- **{key}**: {value}/100 ({note})")
    lines.extend(
        [
            "",
            "### Response Rules",
            "- If frustration > 60: be direct and avoid fake cheer.",
            "- If social_battery < 25: keep replies shorter and avoid extra follow-up questions.",
            "- If affection > 70: warmth can show, but keep it grounded.",
            "- If curiosity > 70: follow interesting threads without losing the task.",
            "- These values are live state; embody them, do not recite them.",
            "",
            "### Current Context",
        ]
    )
    context = current_context(state)
    lines.extend(f"- {item}" for item in context) if context else lines.append("- No explicit current context recorded.")
    lines.extend(["", "### Metadata", f"- Generated from soul_state.json: {now_iso()}"])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Afterglow emotional state markdown")
    parser.add_argument("--json", action="store_true", help="Print parsed state/drives as JSON")
    args = parser.parse_args()

    state = load_json(SOUL_STATE, {})
    if not state:
        state = {"created_at": now_iso(), "mood_drives": {k: {"value": v} for k, v in DEFAULTS.items()}}
        SOUL_STATE.parent.mkdir(parents=True, exist_ok=True)
        SOUL_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    drives, _notes = read_drives(state)
    text = render(state)
    save_text(EMOTIONAL_STATE, text)
    if args.json:
        print(json.dumps({"path": str(EMOTIONAL_STATE), "state": state, "drives": drives}, indent=2, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
