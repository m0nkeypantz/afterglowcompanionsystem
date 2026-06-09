#!/usr/bin/env python3
"""Fast Afterglow recall wrapper for OpenClaw hooks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402


OUTPUT_PATH = afterglow.BRAIN / "afterglow_prompt_recall.md"


def render(query: str, limit: int) -> str:
    results = afterglow.semantic_recall(query, limit=limit)
    context = afterglow.build_response_context([query], limit=min(limit, 6))
    lines = [
        f'## Afterglow Fast Recall for "{query}"',
        f"generated_at: {afterglow.now_iso()}",
        "lane: local_sqlite_fts",
        "scope: this OpenClaw instance; cross-session context is handled by turn_context.py",
        "instruction: Use these memories as timestamped evidence. Current user message wins if memory conflicts.",
        "",
    ]
    if not results:
        lines.append("No matching memories found.")
    else:
        for item in results:
            text = afterglow.one_line(item.get("summary") or item.get("text"), 520)
            lines.append(
                f"- score={float(item.get('score') or 0):.1f} "
                f"evidence={item.get('evidence')} type={item.get('type')} "
                f"when={afterglow.memory_time_label(item.get('timestamp_iso') or item.get('timestamp'))} "
                f"id={item.get('id')} source={item.get('source_kind')}: {text}"
            )
    if context.get("memories"):
        lines.extend(["", "## Live Response Context"])
        for mem in context["memories"][:5]:
            lines.append(
                f"- {mem.get('evidence')} {mem.get('type')} "
                f"score={mem.get('score')} when={mem.get('timestamp')}: {mem.get('text')}"
            )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast local Afterglow recall")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    if args.json:
        results = afterglow.semantic_recall(args.query, limit=args.limit)
        payload = {
            "query": args.query,
            "generated_at": afterglow.now_iso(),
            "lane": "local_sqlite_fts",
            "results": results,
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = render(args.query, args.limit)

    if not args.no_write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(text[:160000], encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
