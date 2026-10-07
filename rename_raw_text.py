#!/usr/bin/env python3
"""Rename text files in ``backend/data/raw_text`` to doc001.txt, doc002.txt, etc.

Files are ordered alphabetically by their current filename before numbering.
Run ``python rename_raw_text.py`` or pass a directory as the first argument.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DIRECTORY = ROOT / "backend" / "data" / "raw_text"


def rename_text_files(directory: Path) -> int:
    if not directory.is_dir():
        print(f"Directory does not exist: {directory}", file=sys.stderr)
        return 1

    files = sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".txt"),
        key=lambda path: path.name.casefold(),
    )
    if not files:
        print(f"No text files found in {directory}")
        return 0

    # Stage all files first so names already matching docNNN.txt cannot collide.
    staged: list[tuple[Path, Path]] = []
    try:
        for source in files:
            temporary = directory / f".rename-{uuid.uuid4().hex}.tmp"
            source.rename(temporary)
            staged.append((source, temporary))

        for index, (source, temporary) in enumerate(staged, start=1):
            destination = directory / f"doc{index:03d}{source.suffix}"
            temporary.rename(destination)
            print(f"{source.name} -> {destination.name}")
    except OSError as exc:
        print(f"Could not rename files: {exc}", file=sys.stderr)
        # Restore staged inputs where possible if a filesystem operation fails.
        for source, temporary in staged:
            if temporary.exists() and not source.exists():
                temporary.rename(source)
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename text files to doc001.txt, doc002.txt, etc.")
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=DEFAULT_DIRECTORY,
        help="directory containing text files (default: backend/data/raw_text)",
    )
    args = parser.parse_args()
    return rename_text_files(args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
