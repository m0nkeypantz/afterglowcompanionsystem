#!/usr/bin/env python3
"""Rotate Afterglow logs without requiring external logrotate."""
from __future__ import annotations

import argparse
import gzip
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import afterglow  # noqa: E402


DEFAULT_LOGS = [
    "afterglow.log",
    "semantic_fact_promotion_audit.jsonl",
    "afterglow_recall_trace.jsonl",
    "afterglow_prompt_leak_audit.log",
    "relationship_graph_refresh.log",
    "afterglow_daemon.log",
]


def rotate_one(path: Path, max_bytes: int, backups: int, compress: bool) -> bool:
    if not path.exists() or path.stat().st_size < max_bytes:
        return False
    for idx in range(backups, 0, -1):
        old_plain = path.with_name(f"{path.name}.{idx}")
        old_gz = path.with_name(f"{path.name}.{idx}.gz")
        next_plain = path.with_name(f"{path.name}.{idx + 1}")
        next_gz = path.with_name(f"{path.name}.{idx + 1}.gz")
        if idx >= backups:
            old_plain.unlink(missing_ok=True)
            old_gz.unlink(missing_ok=True)
            continue
        if old_gz.exists():
            old_gz.replace(next_gz)
        elif old_plain.exists():
            old_plain.replace(next_plain)
    rotated = path.with_name(f"{path.name}.1")
    path.replace(rotated)
    path.touch()
    if compress:
        gz_path = rotated.with_name(f"{rotated.name}.gz")
        with rotated.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        rotated.unlink(missing_ok=True)
    return True


def rotate(max_bytes: int, backups: int, compress: bool) -> list[str]:
    logs_dir = afterglow.WORKSPACE / "logs"
    rotated: list[str] = []
    for name in DEFAULT_LOGS:
        path = logs_dir / name
        if rotate_one(path, max_bytes=max_bytes, backups=backups, compress=compress):
            rotated.append(str(path))
    return rotated


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate Afterglow logs")
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--backups", type=int, default=5)
    parser.add_argument("--no-compress", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    rotated = rotate(max_bytes=args.max_bytes, backups=args.backups, compress=not args.no_compress)
    if not args.quiet:
        print(f"rotated {len(rotated)} log(s)")
        for path in rotated:
            print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
