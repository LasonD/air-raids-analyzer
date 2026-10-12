"""Source registry. Each source has `name`, `role` ("alerts" or "signals"), `fetch()` and
`load() -> SourceData`; adding a source means adding an adapter and registering it here."""
from __future__ import annotations


def registry() -> dict:
    from airraid.sources.etryvoga import EtryvogaAlerts
    from airraid.sources.telegram import TelegramSignals

    sources = [EtryvogaAlerts(), TelegramSignals("kpszsu"), TelegramSignals("povitryanatrivogaaa")]
    return {s.name: s for s in sources}
