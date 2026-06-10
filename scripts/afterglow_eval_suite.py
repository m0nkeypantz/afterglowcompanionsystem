#!/usr/bin/env python3
"""Small regression suite for Afterglow companion-memory behavior."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402
from afterglow_config import load_config  # noqa: E402

try:
    from afterglow_companion_memory import rebuild_all
except Exception:  # pragma: no cover
    rebuild_all = None  # type: ignore[assignment]


CONFIG = load_config()
CASES_PATH = afterglow.BRAIN / "afterglow_eval_cases.json"
REPORT_PATH = afterglow.BRAIN / "afterglow_eval_last.json"


def default_cases() -> list[dict[str, Any]]:
    companion = str(CONFIG.get("companion_name") or "Companion")
    user = str(CONFIG.get("user_name") or "User")
    return [
        {
            "id": "recent_continuity",
            "query": f"recent context about {user} and {companion}",
            "expected_any": ["Afterglow", "memory", "recent"],
            "soft": True,
        },
        {
            "id": "companion_observation_overlay",
            "query": "current companion memory observations",
            "expected_any": ["Companion Memory Overlay", "observation", "episode"],
            "soft": True,
        },
        {
            "id": "project_threads",
            "query": "current projects and unresolved follow ups",
            "expected_any": ["project", "follow", "memory"],
            "soft": True,
        },
    ]


def load_cases() -> list[dict[str, Any]]:
    if CASES_PATH.exists():
        try:
            loaded = json.loads(CASES_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                return loaded
        except Exception:
            pass
    cases = default_cases()
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    return cases


def run_recall(query: str, limit: int) -> tuple[int, str, float]:
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "fast_memory_recall.py"), query, "--limit", str(limit), "--no-write"],
        cwd=str(afterglow.WORKSPACE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return int(proc.returncode), proc.stdout or "", elapsed_ms


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def db_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    with afterglow.connect() as con:
        con.row_factory = sqlite3.Row
        memories = int(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        facts = int(con.execute("SELECT COUNT(*) FROM semantic_facts").fetchone()[0])
        latest = con.execute("SELECT MAX(timestamp_iso) FROM memories").fetchone()[0]
        checks.append({"id": "sqlite_quick_check", "ok": con.execute("PRAGMA quick_check").fetchone()[0] == "ok"})
        checks.append({"id": "memories_present", "ok": memories > 0, "soft": True, "detail": memories})
        checks.append({"id": "semantic_facts_present", "ok": facts > 0, "soft": True, "detail": facts})
        checks.append({"id": "newest_memory_timestamp", "ok": bool(latest), "soft": True, "detail": latest})
        if table_exists(con, "companion_observations"):
            count = int(con.execute("SELECT COUNT(*) FROM companion_observations").fetchone()[0])
            checks.append({"id": "companion_observations_populated", "ok": count > 0, "soft": True, "detail": count})
        else:
            checks.append({"id": "companion_observations_schema", "ok": False, "soft": True, "detail": "not built yet"})
        if table_exists(con, "relationship_edges"):
            count = int(con.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0])
            checks.append({"id": "relationship_edges_available", "ok": count >= 0, "soft": True, "detail": count})
    leak_report = afterglow.BRAIN / "afterglow_prompt_leak_audit.json"
    if leak_report.exists():
        try:
            leaked = json.loads(leak_report.read_text(encoding="utf-8")).get("finding_count", 0)
            checks.append({"id": "prompt_leak_audit_clean", "ok": int(leaked) == 0, "soft": True, "detail": leaked})
        except Exception as exc:
            checks.append({"id": "prompt_leak_audit_readable", "ok": False, "soft": True, "detail": str(exc)})
    return checks


def evaluate(limit: int = 8, rebuild: bool = False) -> dict[str, Any]:
    if rebuild and rebuild_all:
        try:
            rebuild_all()
        except Exception:
            pass
    cases = load_cases()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        rc, output, elapsed_ms = run_recall(str(case.get("query") or ""), limit=limit)
        expected = [str(x).lower() for x in case.get("expected_any") or []]
        lowered = output.lower()
        matched = [word for word in expected if word in lowered]
        ok = rc == 0 and (not expected or bool(matched))
        case_results.append(
            {
                "id": case.get("id"),
                "query": case.get("query"),
                "ok": ok,
                "soft": bool(case.get("soft", False)),
                "elapsed_ms": round(elapsed_ms, 1),
                "matched": matched,
                "expected_any": expected,
                "sample": afterglow.one_line(output, 600),
            }
        )
    checks = db_checks()
    hard_failures = [x for x in [*case_results, *checks] if not x.get("ok") and not x.get("soft")]
    soft_failures = [x for x in [*case_results, *checks] if not x.get("ok") and x.get("soft")]
    payload = {
        "generated_at": afterglow.now_iso(),
        "ok": not hard_failures,
        "hard_failure_count": len(hard_failures),
        "soft_failure_count": len(soft_failures),
        "cases": case_results,
        "checks": checks,
    }
    afterglow.save_json(REPORT_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Afterglow memory regression checks")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict-soft", action="store_true", help="Treat soft failures as non-zero")
    args = parser.parse_args()
    payload = evaluate(limit=args.limit, rebuild=args.rebuild)
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"ok={payload['ok']} hard_failures={payload['hard_failure_count']} soft_failures={payload['soft_failure_count']}")
    if payload["hard_failure_count"] or (args.strict_soft and payload["soft_failure_count"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
