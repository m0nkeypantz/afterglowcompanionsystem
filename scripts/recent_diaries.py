#!/usr/bin/env python3
"""Print recent Afterglow diary entries for prompt context or UI checks."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


ROOT = Path(os.environ.get("OPENCLAW_WORKSPACE") or Path(__file__).resolve().parents[1]).resolve()
DIARY_DIR = Path(os.environ.get("AFTERGLOW_DIARY_DIR") or ROOT / "memory" / "afterglow_diary")


def compact(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: max(0, limit - 3)].rstrip() + "..."


def entries(count: int) -> list[Path]:
    if not DIARY_DIR.exists():
        return []
    return sorted((p for p in DIARY_DIR.glob("*.md") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:count]


def main() -> int:
    parser = argparse.ArgumentParser(description="Show recent Afterglow diary entries")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--chars", type=int, default=700)
    parser.add_argument("--brief", action="store_true")
    args = parser.parse_args()

    files = entries(args.count)
    if not files:
        print("No recent diary entries found.")
        return 0

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if args.brief:
            print(f"- [{path.name}] {compact(text, min(args.chars, 360))}")
        else:
            print(f"## {path.name}")
            print(compact(text, args.chars))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
