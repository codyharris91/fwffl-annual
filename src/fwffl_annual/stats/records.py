"""Category 3 — the record book: scoring extremes, crowns, volatility, splits."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head, regular_season, rows


def crowns(arc: Archive, weeks: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Weeks spent as the league's highest — and lowest — scorer."""
    regular = regular_season(weeks, arc)
    high: Counter[str] = Counter()
    low: Counter[str] = Counter()
    for _, group in regular.groupby(["season", "week"]):
        live = group[group.points > 0]
        if live.empty:
            continue
        high[live.loc[live.points.idxmax()].uid] += 1
        low[live.loc[live.points.idxmin()].uid] += 1

    weeks_played = regular[regular.points > 0].groupby("uid").size()

    def table(counter: Counter[str]) -> list[dict[str, Any]]:
        out = [
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "count": n,
                "weeks": int(weeks_played.get(uid, 0)),
                "rate": round(n / weeks_played[uid] * 100, 1) if weeks_played.get(uid) else 0.0,
            }
            for uid, n in counter.items()
        ]
        out.sort(key=lambda d: -d["count"])
        return out

    return {"high": table(high), "low": table(low)}


def volatility(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """How wildly a manager's weekly score swings, regular season only."""
    regular = regular_season(weeks, arc)
    grouped = regular.groupby("uid").points.agg(["mean", "std", "min", "max", "size"])
    out = []
    for uid, r in grouped.iterrows():
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "average": round(r["mean"], 1),
                "stdev": round(r["std"], 1),
                "floor": round(r["min"], 2),
                "ceiling": round(r["max"], 2),
                "swing": round(r["max"] - r["min"], 1),
                # Coefficient of variation: swing relative to how much you score,
                # so a high-scoring team is not punished for having a big range.
                "cv": round(r["std"] / r["mean"] * 100, 1),
                "weeks": int(r["size"]),
            }
        )
    out.sort(key=lambda d: -d["cv"])
    return out


def season_splits(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Fast starters versus closers: first half of the regular season vs second."""
    regular = regular_season(weeks, arc)
    midpoint = regular.groupby("season").week.max() / 2
    regular = regular.assign(half=regular.week > regular.season.map(midpoint))
    pivot = regular.pivot_table(index="uid", columns="half", values="points", aggfunc="mean")
    pivot = pivot.dropna()
    out = []
    for uid, r in pivot.iterrows():
        first, second = r.get(False), r.get(True)
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "first_half": round(first, 1),
                "second_half": round(second, 1),
                "delta": round(second - first, 1),
            }
        )
    out.sort(key=lambda d: -d["delta"])
    return out


def best_player_weeks(arc: Archive, players: pd.DataFrame, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Biggest individual performances ever rostered in this league."""
    top = players.nlargest(15, "points").copy()
    return rows(top, ["season", "week", "player", "position", "points", "started", "manager"])


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    games = head_to_head(weeks)
    cols = ["season", "week", "manager", "team_name", "points", "opp_manager", "opp_points", "is_playoff"]
    return {
        "highest_weeks": rows(games.nlargest(15, "points"), cols),
        "lowest_weeks": rows(games.nsmallest(12, "points"), cols),
        "best_player_weeks": best_player_weeks(arc, tables["player_weeks"], weeks),
        "crowns": crowns(arc, weeks),
        "volatility": volatility(arc, weeks),
        "splits": season_splits(arc, weeks),
    }
