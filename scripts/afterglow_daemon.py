#!/usr/bin/env python3
"""Fallback Afterglow ingester.

This keeps local memory moving even if a plugin hook misses a message. It polls
OpenClaw session JSONL files and periodically promotes semantic facts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

SCRIPT_DIR = Path(__file__).resolve().parent
AFTERGLOW = SCRIPT_DIR / "afterglow.py"
HINDSIGHT_MIRROR = SCRIPT_DIR / "hindsight_mirror.py"
LOG = SCRIPT_DIR.parent / "logs" / "afterglow_daemon.log"


def log(event: dict) -> None:
    event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_afterglow(args: list[str], timeout: int = 60) -> dict:
    cmd = [sys.executable, str(AFTERGLOW), *args]
    started = time.time()
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    return {
        "cmd": args,
        "returncode": proc.returncode,
        "elapsed_ms": int((time.time() - started) * 1000),
        "stdout": proc.stdout[-1200:],
        "stderr": proc.stderr[-1200:],
    }


def cycle(max_files: int, promote_every: int | None, import_local_every: int | None, cycle_no: int) -> None:
    cmd = ["ingest-sessions", "--max-files", str(max_files)]
    log(run_afterglow(cmd, timeout=60))
    if promote_every and cycle_no % promote_every == 0:
        log(run_afterglow(["promote-facts", "--limit", "7000"], timeout=120))
    if import_local_every and cycle_no % import_local_every == 0:
        log(run_afterglow(["import-local", "--no-sessions"], timeout=120))
    if HINDSIGHT_MIRROR.exists() and cycle_no % 3 == 0:
        cmd = [sys.executable, str(HINDSIGHT_MIRROR), "--limit", "20"]
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        log({
            "cmd": ["hindsight_mirror.py", "--limit", "20"],
            "returncode": proc.returncode,
            "stdout": proc.stdout[-1200:],
            "stderr": proc.stderr[-1200:],
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="Afterglow fallback polling daemon")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--max-files", type=int, default=30)
    parser.add_argument("--promote-every", type=int, default=12, help="Every N cycles; 0 disables")
    parser.add_argument("--import-local-every", type=int, default=24, help="Every N cycles; 0 disables")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cycle_no = 1
    import_every = args.import_local_every if args.import_local_every > 0 else None
    promote_every = args.promote_every if args.promote_every > 0 else None
    while True:
        try:
            cycle(args.max_files, promote_every, import_every, cycle_no)
        except subprocess.TimeoutExpired as exc:
            log({"event": "timeout", "cmd": getattr(exc, "cmd", []), "timeout": exc.timeout})
        except Exception as exc:
            log({"event": "error", "error": str(exc)})
        if args.once:
            return 0
        cycle_no += 1
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
