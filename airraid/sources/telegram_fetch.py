"""Download raw pages of a public Telegram channel's web preview (t.me/s/<channel>).

Each preview page holds ~20 posts below a given id (`?before=<id>`), so the id range from
`since` to the newest post is split into pages and fetched in parallel. Pages are cached
gzipped and named by the oldest post id they contain; already covered ids are skipped,
so re-running tops up new posts and fills gaps. Parsing happens separately.

Usage: python -m airraid.sources.telegram_fetch <channel> <since YYYY-MM-DD> [workers]
"""
from __future__ import annotations

import gzip
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

PREVIEW_URL = "https://t.me/s/{channel}"
POST_RE = re.compile(r'data-post="[^/]+/(\d+)".*?<time datetime="([^"]+)"', re.S)
USER_AGENT = "Mozilla/5.0 (compatible; air-raids-analyzer research)"
DEFAULT_CACHE = Path("data/raw/telegram")
PAGE_SIZE = 20


def _get(url: str, retries: int = 6) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            wait = 5 * 2**attempt + random.random()
            print(f"  {exc}; retry in {wait:.0f}s", file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def _posts(page: str) -> list[tuple[int, datetime]]:
    return [(int(i), datetime.fromisoformat(d)) for i, d in POST_RE.findall(page)]


def _page(channel: str, before: int | None = None) -> tuple[str, list[tuple[int, datetime]]]:
    page = _get(PREVIEW_URL.format(channel=channel) + (f"?before={before}" if before else ""))
    return page, _posts(page)


def _id_at(channel: str, when: datetime, newest: int) -> int:
    """Binary search for roughly the first post id published at or after `when`."""
    lo, hi = 1, newest
    while hi - lo > PAGE_SIZE:
        mid = (lo + hi) // 2
        _, posts = _page(channel, mid)
        if posts and min(posts)[1] >= when:
            hi = mid
        else:
            lo = mid
    return lo


def _covered_ids(out: Path) -> set[int]:
    ids: set[int] = set()
    for f in out.glob("*.html.gz"):
        ids.update(i for i, _ in _posts(gzip.decompress(f.read_bytes()).decode("utf-8")))
    return ids


def fetch(channel: str, since: datetime, cache_dir: Path = DEFAULT_CACHE, workers: int = 6) -> None:
    out = cache_dir / channel
    out.mkdir(parents=True, exist_ok=True)
    _, newest_posts = _page(channel)
    newest = max(newest_posts)[0]
    first = _id_at(channel, since, newest)
    covered = _covered_ids(out)
    # A page fetched with before=b holds the ~20 existing posts below b; stepping by 20
    # therefore covers every id. Deleted ids look uncovered and cost a redundant request.
    todo = [b for b in range(newest + 1, first, -PAGE_SIZE)
            if any(i not in covered for i in range(b - PAGE_SIZE, b))]
    print(f"{channel}: ids {first}..{newest}, {len(todo)} pages to fetch with {workers} workers", flush=True)

    def one(before: int) -> int:
        time.sleep(random.uniform(0.3, 1.0))
        page, posts = _page(channel, before)
        if posts:
            (out / f"{min(posts)[0]}.html.gz").write_bytes(gzip.compress(page.encode("utf-8")))
        return len(posts)

    done = empty = 0
    with ThreadPoolExecutor(workers) as pool:
        for n in pool.map(one, todo):
            done += 1
            empty += n == 0
            if done % 100 == 0 or done == len(todo):
                print(f"{channel}: {done}/{len(todo)} pages, {empty} empty", flush=True)
    print(f"{channel}: done", flush=True)


if __name__ == "__main__":
    channel = sys.argv[1]
    since = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=timezone.utc)
    fetch(channel, since, workers=int(sys.argv[3]) if len(sys.argv) > 3 else 6)
