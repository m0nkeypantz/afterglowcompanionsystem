#!/usr/bin/env python3
"""Manual/deep Afterglow recall tool for OpenClaw."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall memories from the local Afterglow DB")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--expand", action="store_true", help="Include neighboring memories from the same source file")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    results = afterglow.semantic_recall(args.query, limit=args.limit)
    if args.expand:
        for item in results:
            item["expanded_context"] = afterglow.expand_memory_context(str(item.get("id") or ""), window=3)

    if args.json:
        text = json.dumps(
            {
                "query": args.query,
                "generated_at": afterglow.now_iso(),
                "lane": "afterglow_deep_recall",
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    else:
        header = [
            f'## Afterglow Deep Recall for "{args.query}"',
            f"generated_at: {afterglow.now_iso()}",
            "lane: local_afterglow_deep",
            "scope: this OpenClaw instance; cross-session context is handled by turn_context.py",
            "instruction: Treat each row as timestamped evidence. Do not invent facts beyond the evidence.",
            "",
        ]
        text = "\n".join(header) + afterglow.format_recall(args.query, results) + "\n"

    if not args.no_write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(text[:160000], encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
