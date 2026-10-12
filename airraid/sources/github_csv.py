"""Download alert CSVs from Vadimkin/ukrainian-air-raid-sirens-dataset, pinned to a commit.

The upstream repo is rewritten daily, so a commit SHA (not `main`) makes runs reproducible.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

from airraid.paths import RAW

REPO = "Vadimkin/ukrainian-air-raid-sirens-dataset"
# Snapshot of 2026-10-12 05:05 UTC (volunteer data through 2026-10-12; official stops 2026-09-07).
PINNED_SHA = "d10c80fa696bab42822b9f05b423fc8a30e79d20"
# The dump has no open intervals, so alerts still running at 05:05 are missing; keep a margin.
COMPLETE_UNTIL = pd.Timestamp("2026-10-12 00:00", tz="UTC")
RAW_URL = "https://raw.githubusercontent.com/{repo}/{sha}/datasets/{name}"
DEFAULT_CACHE = RAW / "alerts"


def fetch(name: str, sha: str = PINNED_SHA, cache_dir: Path = DEFAULT_CACHE) -> Path:
    """Download `datasets/<name>` at `sha` once and return the local path."""
    path = cache_dir / sha[:7] / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(RAW_URL.format(repo=REPO, sha=sha, name=name), timeout=120) as resp:
            path.write_bytes(resp.read())
    return path
