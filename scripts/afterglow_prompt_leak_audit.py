#!/usr/bin/env python3
"""Audit Afterglow stores for prompt-wrapper or operational-context leaks."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402


REPORT_PATH = afterglow.BRAIN / "afterglow_prompt_leak_audit.json"
LEAK_PATTERNS = {
    "bridge_context": re.compile(r"<bridge_system_context|</bridge_system_context>", re.I),
    "turn_context": re.compile(r"Mandatory Turn Context|generated_by:\s*afterglow-memory", re.I),
    "thinking_header": re.compile(r"\[(?:Text|OpenClaw)-Thinking", re.I),
    "prompt_instruction": re.compile(r"Only the text inside|not\s+(?:the\s+)?user speaking|do not quote it", re.I),
    "tool_primer": re.compile(r"tool usage:|available commands|system prompt", re.I),
    "credential_chatter": re.compile(r"\b(?:api key|secret key|bearer token|ssh key)\b", re.I),
}


def one_line(value: Any, limit: int = 260) -> str:
    return afterglow.one_line(str(value or ""), limit)


def match_labels(text: str) -> list[str]:
    return [name for name, pattern in LEAK_PATTERNS.items() if pattern.search(text or "")]


def audit(limit: int = 100) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    with afterglow.connect() as con:
        con.row_factory = sqlite3.Row
        memory_rows = con.execute(
            """
            SELECT id, type, timestamp_iso, source_kind, source_path, summary, text
            FROM memories
            ORDER BY timestamp_iso DESC
            LIMIT 20000
            """
        ).fetchall()
        for row in memory_rows:
            text = f"{row['summary'] or ''}\n{row['text'] or ''}"
            labels = match_labels(text)
            if labels:
                findings.append(
                    {
                        "store": "memories",
                        "id": row["id"],
                        "type": row["type"],
                        "timestamp": row["timestamp_iso"],
                        "source_kind": row["source_kind"],
                        "source_path": row["source_path"],
                        "labels": labels,
                        "sample": one_line(text),
                    }
                )
            if len(findings) >= limit:
                break
        if len(findings) < limit:
            fact_rows = con.execute(
                """
                SELECT id, subject, predicate, object, status, updated_at, summary, text, contextual_text
                FROM semantic_facts
                ORDER BY updated_at DESC
                LIMIT 20000
                """
            ).fetchall()
            for row in fact_rows:
                text = f"{row['subject']} {row['predicate']} {row['object']}\n{row['summary'] or ''}\n{row['text'] or ''}\n{row['contextual_text'] or ''}"
                labels = match_labels(text)
                if labels:
                    findings.append(
                        {
                            "store": "semantic_facts",
                            "id": row["id"],
                            "status": row["status"],
                            "timestamp": row["updated_at"],
                            "labels": labels,
                            "sample": one_line(text),
                        }
                    )
                if len(findings) >= limit:
                    break
    counts: dict[str, int] = {}
    for item in findings:
        for label in item["labels"]:
            counts[label] = counts.get(label, 0) + 1
    payload = {
        "generated_at": afterglow.now_iso(),
        "db": str(afterglow.DB_PATH),
        "finding_count": len(findings),
        "label_counts": counts,
        "findings": findings,
        "ok": not findings,
    }
    afterglow.save_json(REPORT_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Afterglow memory stores for prompt leaks")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if findings are present")
    args = parser.parse_args()
    payload = audit(limit=args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"prompt leak findings: {payload['finding_count']}")
        for item in payload["findings"][:20]:
            print(f"- {item['store']} {item['id']} labels={','.join(item['labels'])}: {item['sample']}")
    return 1 if args.strict and payload["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
