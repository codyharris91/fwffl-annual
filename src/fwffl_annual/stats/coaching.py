"""Category 4 — start/sit: how well managers actually set their lineups.

Efficiency is points scored as a share of the best legal lineup available from
that roster that week. It is the one number here that is purely about managing
rather than about who you drafted or who you played.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head, rows


def efficiency(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    played = weeks[weeks.optimal > 0]
    grouped = played.groupby("uid").agg(
        weeks=("efficiency", "size"),
        efficiency=("efficiency", "mean"),
        left_total=("left_on_bench", "sum"),
        left_per_week=("left_on_bench", "mean"),
    )
    perfect = played[played.efficiency >= 99.99].groupby("uid").size()
    out = []
    for uid, r in grouped.iterrows():
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "weeks": int(r.weeks),
                "efficiency": round(r.efficiency, 2),
                "left_total": round(r.left_total, 1),
                "left_per_week": round(r.left_per_week, 2),
                "perfect_weeks": int(perfect.get(uid, 0)),
            }
        )
    out.sort(key=lambda d: -d["efficiency"])
    return out


def _biggest_miss(arc: Archive, row: Any) -> tuple[str | None, float]:
    """The benched player who most should have started that week."""
    points = json.loads(row.player_points)
    started = set(json.loads(row.starters))
    benched = [(pid, v) for pid, v in points.items() if pid not in started]
    if not benched:
        return None, 0.0
    pid, value = max(benched, key=lambda kv: kv[1])
    return arc.player_name(pid), round(float(value), 2)


def bench_disasters(arc: Archive, weeks: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """Weeks where the most points were left sitting on the bench."""
    worst = weeks.nlargest(limit, "left_on_bench")
    out = []
    for r in worst.itertuples():
        name, value = _biggest_miss(arc, r)
        out.append(
            {
                "season": r.season,
                "week": r.week,
                "manager": r.manager,
                "points": round(r.points, 2),
                "optimal": round(r.optimal, 2),
                "left": round(r.left_on_bench, 2),
                "biggest_miss": name,
                "miss_points": value,
                "opp_manager": r.opp_manager,
                "opp_points": None if pd.isna(r.opp_points) else round(r.opp_points, 2),
                "cost_the_game": bool(
                    not pd.isna(r.opp_points) and r.points < r.opp_points <= r.optimal
                ),
            }
        )
    return out


def coaching_losses(arc: Archive, weeks: pd.DataFrame) -> dict[str, Any]:
    """Losses the manager's own best lineup would have won.

    Not hindsight bias for its own sake — this is the subset of losses that were
    decided by the start/sit call rather than by the roster.
    """
    games = head_to_head(weeks)
    blown = games[games.lost & (games.optimal > games.opp_points)]
    tally = blown.groupby("uid").size().sort_values(ascending=False)
    losses = games[games.lost].groupby("uid").size()

    table = [
        {
            "uid": uid,
            "manager": arc.manager(uid),
            "count": int(n),
            "losses": int(losses.get(uid, 0)),
            "share": round(n / losses[uid] * 100, 1) if losses.get(uid) else 0.0,
        }
        for uid, n in tally.items()
    ]

    worst = []
    for r in blown.nlargest(10, "left_on_bench").itertuples():
        name, value = _biggest_miss(arc, r)
        worst.append(
            {
                "season": r.season,
                "week": r.week,
                "manager": r.manager,
                "points": round(r.points, 2),
                "optimal": round(r.optimal, 2),
                "opp_manager": r.opp_manager,
                "opp_points": round(r.opp_points, 2),
                "biggest_miss": name,
                "miss_points": value,
            }
        )
    return {"by_manager": table, "worst": worst}


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    played = weeks[weeks.optimal > 0]
    return {
        "efficiency": efficiency(arc, weeks),
        "bench_disasters": bench_disasters(arc, weeks),
        "coaching_losses": coaching_losses(arc, weeks),
        "perfect_lineups": rows(
            played[played.efficiency >= 99.99].nlargest(10, "points"),
            ["season", "week", "manager", "points", "optimal"],
        ),
    }
