"""Shared filters and helpers for the stat modules.

Two distinctions matter everywhere and are easy to get wrong:

*Real games* are rows with an opponent. Sleeper reports a score for every team
in every week, including teams sitting out the playoffs and the dead week after
the final, so anything ranking "worst score ever" must filter on an opponent
existing or it just finds weeks nobody set a lineup.

*Regular season* is weeks before `playoff_week_start`. Rate stats use it because
playoff weeks only involve six teams, and the other six are not trying.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..archive import Archive


def head_to_head(weeks: pd.DataFrame) -> pd.DataFrame:
    """Only rows that were an actual matchup against an opponent."""
    return weeks[weeks.opp_points.notna()]


def regular_season(weeks: pd.DataFrame, arc: Archive) -> pd.DataFrame:
    """Weeks before the playoffs started, per that season's own settings."""
    cutoff = weeks.season.map({s.year: s.playoff_week for s in arc.completed})
    return weeks[weeks.week < cutoff]


def rows(df: pd.DataFrame, columns: list[str], limit: int | None = None) -> list[dict[str, Any]]:
    """DataFrame -> list of plain dicts, JSON-safe."""
    out = df[columns].head(limit) if limit else df[columns]
    return [
        {k: (None if pd.isna(v) else (round(v, 2) if isinstance(v, float) else v)) for k, v in r.items()}
        for r in out.to_dict("records")
    ]


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def pick_label(pick: int, teams: int) -> str:
    """Overall pick 27 in a 12-team league -> '3.03'."""
    rnd = (pick - 1) // teams + 1
    slot = (pick - 1) % teams + 1
    return f"{rnd}.{slot:02d}"
