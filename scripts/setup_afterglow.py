#!/usr/bin/env python3
"""Interactive installer for Afterglow Companion System."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_SRC = REPO_ROOT / "scripts"
PLUGIN_SRC = REPO_ROOT / "plugins" / "afterglow-memory"


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "__pycache__" or item.suffix == ".pyc":
            continue
        target = dst / item.name
        if item.is_dir():
            copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def configure_openclaw(openclaw_json: Path) -> Path:
    cfg = load_json(openclaw_json, {})
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Invalid JSON object at {openclaw_json}")
    backup = openclaw_json.with_name(f"{openclaw_json.name}.before-afterglow.bak")
    if openclaw_json.exists():
        shutil.copy2(openclaw_json, backup)

    gateway = ensure_dict(cfg, "gateway")
    gateway.setdefault("mode", "local")

    plugins = ensure_dict(cfg, "plugins")
    slots = ensure_dict(plugins, "slots")
    slots["memory"] = "none"
    entries = ensure_dict(plugins, "entries")
    entries["memory-core"] = {"enabled": False}
    entries["memory-wiki"] = {"enabled": False}
    entries["afterglow-memory"] = {"enabled": True}

    tools = ensure_dict(cfg, "tools")
    deny = list(tools.get("deny") or [])
    for item in ("memory_*", "wiki_*", "brain__*"):
        if item not in deny:
            deny.append(item)
    tools["deny"] = deny
    tools.setdefault(
        "loopDetection",
        {
            "enabled": True,
            "historySize": 20,
            "warningThreshold": 5,
            "criticalThreshold": 8,
            "unknownToolThreshold": 3,
            "globalCircuitBreakerThreshold": 12,
        },
    )

    hooks = ensure_dict(cfg, "hooks")
    internal = ensure_dict(hooks, "internal")
    hook_entries = ensure_dict(internal, "entries")
    hook_entries["session-memory"] = {"enabled": False}

    if isinstance(cfg.get("mcp"), dict):
        servers = cfg["mcp"].get("servers")
        if isinstance(servers, dict) and isinstance(servers.get("brain"), dict):
            servers["brain"]["enabled"] = False

    save_json(openclaw_json, cfg)
    return backup


def write_afterglow_config(workspace: Path, args: argparse.Namespace) -> Path:
    config_path = workspace / "brain" / "afterglow_config.json"
    existing = load_json(config_path, {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update(
        {
            "companion_name": args.companion_name,
            "user_name": args.user_name,
            "timezone": args.timezone,
            "models": {
                "pulse": args.pulse_model,
                "diary": args.diary_model,
                "reflection": args.reflection_model,
                "recall": "local_sqlite_fts",
            },
            "model_runner": {
                "command_template": args.model_command_template,
                "timeout_seconds": args.model_timeout,
                "notes": "Template fields: {model}, {session_key}, {prompt_path}, {output_path}. Leave empty to generate local diary fallbacks without model calls.",
            },
            "pulse": {
                "enabled": args.enable_pulse,
                "interval_minutes": args.pulse_interval,
                "diary_on_pulse": True,
                "outreach_enabled": args.enable_outreach,
                "quiet_hours_start": 22,
                "quiet_hours_end": 7,
            },
            "companion_memory": {
                "enabled": True,
                "observation_scan_limit": 6000,
                "episode_days": 21,
                "small_stuff_limit": 12,
                "relationship_edge_days": 30,
                "relationship_core_entities": [],
                "custom_relationship_predicates": [],
                "prompt_leak_quarantine": True,
                "trace_recall": True,
            },
            "ui": {"host": "127.0.0.1", "port": args.ui_port},
        }
    )
    save_json(config_path, existing)
    return config_path


def run_python(script: Path, args: list[str], workspace: Path, state_dir: Path) -> int:
    env = os.environ.copy()
    env["OPENCLAW_WORKSPACE"] = str(workspace)
    env["OPENCLAW_STATE_DIR"] = str(state_dir)
    proc = subprocess.run([sys.executable, str(script), *args], cwd=str(workspace), env=env)
    return int(proc.returncode)


def install(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else state_dir / "workspace"
    openclaw_json = Path(args.openclaw_json).expanduser().resolve() if args.openclaw_json else state_dir / "openclaw.json"

    (workspace / "scripts").mkdir(parents=True, exist_ok=True)
    (workspace / "brain" / "memory_index").mkdir(parents=True, exist_ok=True)
    (workspace / "memory" / "afterglow_diary").mkdir(parents=True, exist_ok=True)
    copy_tree(SCRIPTS_SRC, workspace / "scripts")

    # OpenClaw versions have looked in both locations across builds.
    copy_tree(PLUGIN_SRC, state_dir / "plugins" / "afterglow-memory")
    copy_tree(PLUGIN_SRC, workspace / "plugins" / "afterglow-memory")

    config_path = write_afterglow_config(workspace, args)
    backup = configure_openclaw(openclaw_json) if openclaw_json.exists() else None

    env = os.environ.copy()
    env["OPENCLAW_WORKSPACE"] = str(workspace)
    env["OPENCLAW_STATE_DIR"] = str(state_dir)
    env["OPENCLAW_SESSIONS_DIR"] = str(state_dir / "agents" / "main" / "sessions")
    subprocess.run([sys.executable, str(workspace / "scripts" / "render_emotional_state.py")], cwd=str(workspace), env=env, check=False)

    imported = None
    if args.import_openclaw:
        rc = run_python(
            workspace / "scripts" / "afterglow.py",
            ["import-local", "--promote-facts", "--fact-limit", str(args.fact_limit), "--max-session-files", str(args.max_session_files)],
            workspace,
            state_dir,
        )
        imported = {"openclaw": rc}
    if args.hindsight_export:
        rc = run_python(
            workspace / "scripts" / "afterglow.py",
            ["import-hindsight", str(Path(args.hindsight_export).expanduser()), "--promote-facts", "--fact-limit", str(args.fact_limit)],
            workspace,
            state_dir,
        )
        imported = {**(imported or {}), "hindsight": rc}

    companion_overlay = run_python(workspace / "scripts" / "afterglow_companion_memory.py", ["rebuild"], workspace, state_dir)
    relationship_graph = run_python(workspace / "scripts" / "afterglow_relationship_refresh.py", [], workspace, state_dir)

    return {
        "state_dir": str(state_dir),
        "workspace": str(workspace),
        "openclaw_json": str(openclaw_json),
        "openclaw_backup": str(backup) if backup else "",
        "config": str(config_path),
        "plugin_state_path": str(state_dir / "plugins" / "afterglow-memory"),
        "plugin_workspace_path": str(workspace / "plugins" / "afterglow-memory"),
        "imported": imported,
        "companion_overlay": companion_overlay,
        "relationship_graph": relationship_graph,
    }


def interactive_defaults(args: argparse.Namespace) -> argparse.Namespace:
    if args.non_interactive:
        return args
    default_state = str(Path.home() / ".openclaw")
    args.state_dir = prompt("OpenClaw state dir", args.state_dir or default_state)
    args.workspace = prompt("OpenClaw workspace", args.workspace or str(Path(args.state_dir).expanduser() / "workspace"))
    args.openclaw_json = prompt("openclaw.json path", args.openclaw_json or str(Path(args.state_dir).expanduser() / "openclaw.json"))
    args.companion_name = prompt("Companion display name", args.companion_name)
    args.user_name = prompt("User display name", args.user_name)
    args.timezone = prompt("Timezone", args.timezone)
    args.pulse_model = prompt("Model for pulse jobs", args.pulse_model)
    args.diary_model = prompt("Model for diary/reflection jobs", args.diary_model)
    args.reflection_model = prompt("Model for semantic reflection jobs", args.reflection_model)
    args.model_command_template = prompt("Optional model command template", args.model_command_template)
    args.enable_pulse = yes_no("Enable autonomous pulse loop config", args.enable_pulse)
    args.enable_outreach = yes_no("Enable proactive outreach drafts", args.enable_outreach)
    args.import_openclaw = yes_no("Import existing OpenClaw memory/session files now", args.import_openclaw)
    if yes_no("Import a Hindsight export JSON now", False):
        args.hindsight_export = prompt("Path to Hindsight export JSON", args.hindsight_export)
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Afterglow Companion System into OpenClaw")
    parser.add_argument("--state-dir", default=str(Path.home() / ".openclaw"))
    parser.add_argument("--workspace")
    parser.add_argument("--openclaw-json")
    parser.add_argument("--companion-name", default="Companion")
    parser.add_argument("--user-name", default="User")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--pulse-model", default="openrouter/auto")
    parser.add_argument("--diary-model", default="openrouter/auto")
    parser.add_argument("--reflection-model", default="openrouter/auto")
    parser.add_argument("--model-command-template", default="")
    parser.add_argument("--model-timeout", type=int, default=120)
    parser.add_argument("--pulse-interval", type=int, default=72)
    parser.add_argument("--ui-port", type=int, default=8765)
    parser.add_argument("--enable-pulse", action="store_true")
    parser.add_argument("--enable-outreach", action="store_true")
    parser.add_argument("--import-openclaw", action="store_true")
    parser.add_argument("--hindsight-export")
    parser.add_argument("--fact-limit", type=int, default=3000)
    parser.add_argument("--max-session-files", type=int, default=200)
    parser.add_argument("--non-interactive", action="store_true")
    args = interactive_defaults(parser.parse_args())

    result = install(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    print("Next commands:")
    print(f"  python \"{Path(result['workspace']) / 'scripts' / 'afterglow.py'}\" summary")
    print(f"  python \"{Path(result['workspace']) / 'scripts' / 'afterglow_companion_memory.py'}\" rebuild --json")
    print(f"  python \"{Path(result['workspace']) / 'scripts' / 'afterglow_recall_dashboard.py'}\" --json")
    print(f"  python \"{Path(result['workspace']) / 'scripts' / 'turn_context.py'}\" \"recent important context\" --compact")
    print(f"  python \"{Path(result['workspace']) / 'scripts' / 'ui_server.py'}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
