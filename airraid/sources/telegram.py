"""Telegram signal sources: rule-based classification of posts into kinds and regions.

Rules are ordered (first match wins) and were written from the observed post templates of
each channel. Posts that carry no threat information (summaries, maps, damage reports) are
dropped; short follow-ups without a threat type inherit the kind of the previous post.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from airraid.regions import find_regions
from airraid.schema import SourceData, validate
from airraid.sources import telegram_fetch
from airraid.sources.telegram_parse import load_posts

DROP = "drop"
FOLLOW_UP = "follow_up"

# Shared ordered rules: (kind, pattern). Checked after the channel's drop rules.
RULES: list[tuple[str, re.Pattern]] = [(k, re.compile(p)) for k, p in [
    ("clear", r"[Вв]ідбій|\bчисто\b|не фіксу|загроза минула"),
    ("aviation", r"МіГ-31|Ту-(?:95|22|160)|стратегічн\w* авіац"),
    ("ballistic", r"[Бб]аліст|[Шш]видкісн|Іскандер|Кинджал"),
    ("guided_bomb", r"КАБ|керован\w* авіа\w* бомб|💣"),
    ("missile", r"[Рр]акет|[Бб]андерол|[Кк]рилат|Калібр|\bХ-\d+|🚀"),
    ("aviation", r"тактичн\w* авіац|авіаційн\w* засоб\w* ураження|🛫|🛬"),
    ("jet_drone", r"[Рр]еактивн|🏍"),
    ("drone", r"БпЛА|БПЛА|[Дд]рон|[Шш]ахед|🛵|🛸|✈️"),
    ("explosion", r"💥|[Вв]ибух"),
]]

CHANNEL_DROP = {
    "kpszsu": re.compile(r"ЗБИТО|ПОДАВЛЕНО|^⚡"),
    "povitryanatrivogaaa": re.compile(
        r"ЗБИТО|ПОДАВЛЕНО|Карта повітряних тривог|^💔|Попередн\w* (?:по|наслідк)|дорозвідк|Зеленськ"),
}
FOLLOW_UP_WINDOW = pd.Timedelta("60min")


def classify(text: str, channel: str) -> str:
    if CHANNEL_DROP[channel].search(text):
        return DROP
    for kind, rx in RULES:
        if rx.search(text):
            return kind
    return FOLLOW_UP


@dataclass
class TelegramSignals:
    channel: str

    role = "signals"

    @property
    def name(self) -> str:
        return self.channel

    def fetch(self, since: str = "2026-01-01") -> None:
        telegram_fetch.fetch(self.channel, pd.Timestamp(since, tz="UTC"))

    def classified_posts(self) -> pd.DataFrame:
        """One row per post with its kind (incl. drop/follow-up) and regions; for diagnostics."""
        posts = load_posts(self.channel)
        posts["kind"] = [classify(t, self.channel) for t in posts["text"]]
        posts["regions"] = [find_regions(t) for t in posts["text"]]
        # A follow-up ("На Боярку") continues the previous threat post if it came shortly after and
        # names a place; anything else without a threat type (greetings, news) is dropped.
        prev_kind = posts["kind"].where(~posts["kind"].isin([DROP, FOLLOW_UP])).ffill()
        prev_time = posts["published_at_utc"].where(~posts["kind"].isin([DROP, FOLLOW_UP])).ffill()
        is_follow = posts["kind"] == FOLLOW_UP
        inherit = is_follow & ((posts["published_at_utc"] - prev_time) <= FOLLOW_UP_WINDOW) & (posts["regions"].str.len() > 0)
        posts.loc[inherit, "kind"] = prev_kind[inherit]
        posts.loc[is_follow & ~inherit, "kind"] = DROP
        return posts

    def load(self) -> SourceData:
        posts = self.classified_posts()
        covered_from = posts["published_at_utc"].min().ceil("h")
        covered_to = posts["published_at_utc"].max().floor("h")
        kept = posts[~posts["kind"].isin([DROP, FOLLOW_UP])].copy()
        # One row per region named; posts naming no region keep a single row with region None.
        kept["region"] = kept["regions"].map(lambda r: r or [None])
        df = kept.explode("region")[["published_at_utc", "region", "kind", "ref", "edited"]]
        return validate(SourceData(self.name, "signals", df.reset_index(drop=True), covered_from, covered_to))
