"""Turn cached t.me/s preview pages into a clean table of posts (shared by all Telegram sources)."""
from __future__ import annotations

import gzip
import html
import re
from pathlib import Path

import pandas as pd

from airraid.sources.telegram_fetch import DEFAULT_CACHE

_MESSAGE_SPLIT = '<div class="tgme_widget_message_wrap'
_POST_ID = re.compile(r'data-post="[^/]+/(\d+)"')
_TIME = re.compile(r'<time datetime="([^"]+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_EDITED = re.compile(r'tgme_widget_message_meta">\s*edited')
_PHOTO = re.compile(r"tgme_widget_message_photo_wrap|tgme_widget_message_video")

# Latin letters that look like Cyrillic ones; some channels mix them in ("Kиїв", "БПЛA").
_HOMOGLYPHS = str.maketrans("ABCEHIKMOPTXaceiopxy", "АВСЕНІКМОРТХасеіорху")
_CYRILLIC = re.compile(r"[А-Яа-яЇїІіЄєҐґ]")
_WORD = re.compile(r"[^\W\d_]+")
# An "UPD" appended by a later edit carries information from after the publish time.
_UPDATE = re.compile(r"\s*(?:\bUPD\b|\bUpd\b|\bupd\b|Оновлено|ОНОВЛЕНО).*", re.S)


def _fix_homoglyphs(text: str) -> str:
    return _WORD.sub(lambda m: m.group().translate(_HOMOGLYPHS) if _CYRILLIC.search(m.group()) else m.group(), text)


def normalize(text: str, edited: bool = False) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = _fix_homoglyphs(text.replace("’", "'").replace("ʼ", "'").replace("`", "'"))
    if edited:
        m = _UPDATE.search(text)
        if m and m.start() > 0:
            text = text[: m.start()]
    return re.sub(r"[ \t ]+", " ", text).strip()


def parse_page(page: str) -> list[dict]:
    rows = []
    for block in page.split(_MESSAGE_SPLIT)[1:]:
        pid, ts = _POST_ID.search(block), _TIME.search(block)
        if not (pid and ts):
            continue
        body = _TEXT.search(block)
        edited = bool(_EDITED.search(block))
        rows.append({
            "ref": int(pid.group(1)),
            "published_at_utc": ts.group(1),
            "text": normalize(body.group(1), edited) if body else "",
            "edited": edited,
            "has_media": bool(_PHOTO.search(block)),
        })
    return rows


def load_posts(channel: str, cache_dir: Path = DEFAULT_CACHE) -> pd.DataFrame:
    """All cached posts of a channel, one row per post id, sorted by publish time."""
    rows = []
    for f in (cache_dir / channel).glob("*.html.gz"):
        rows.extend(parse_page(gzip.decompress(f.read_bytes()).decode("utf-8")))
    df = pd.DataFrame(rows).drop_duplicates("ref")
    df["published_at_utc"] = pd.to_datetime(df["published_at_utc"], utc=True)
    return df.sort_values("published_at_utc").reset_index(drop=True)
