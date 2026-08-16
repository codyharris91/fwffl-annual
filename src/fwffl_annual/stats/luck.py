"""Category 2 — luck and injustice.

The core idea is the *all-play record*: what your record would be if you played
every other team every week instead of the one the schedule handed you. The gap
between that and your real record is schedule luck, and over six seasons it is
worth several wins to some managers.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head, regular_season, rows


def all_play(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Every manager's record against the whole league, week by week.

    Regular season only: in playoff weeks the six eliminated teams are still
    scored by Sleeper but are not trying, which would flatter everyone else.
    """
    regular = regular_season(weeks, arc)
    records: list[dict[str, Any]] = []
    for (_, _), group in regular.groupby(["season", "week"]):
        live = group[group.points > 0]
        for r in live.itertuples():
            records.append(
                {
                    "uid": r.uid,
                    "beat": int((live.points < r.points).sum()),
                    "lost_to": int((live.points > r.points).sum()),
                }
            )
    frame = pd.DataFrame(records).groupby("uid").agg(
        all_play_wins=("beat", "sum"), all_play_losses=("lost_to", "sum")
    )

    actual = head_to_head(regular).groupby("uid").agg(
        wins=("won", "sum"), games=("won", "size")
    )
    joined = frame.join(actual).dropna()

    out = []
    for uid, r in joined.iterrows():
        all_play_pct = r.all_play_wins / (r.all_play_wins + r.all_play_losses) * 100
        actual_pct = r.wins / r.games * 100
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "games": int(r.games),
                "all_play_wins": int(r.all_play_wins),
                "all_play_losses": int(r.all_play_losses),
                "all_play_pct": round(all_play_pct, 1),
                "actual_pct": round(actual_pct, 1),
                "luck": round(actual_pct - all_play_pct, 1),
                # Wins gained or lost purely from who the schedule matched you with.
                "wins_swing": round((actual_pct - all_play_pct) / 100 * r.games, 1),
            }
        )
    out.sort(key=lambda d: -d["luck"])
    return out


def _label(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["matchup"] = df.apply(
        lambda r: f"{r.manager} {r.points:.2f} — {r.opp_points:.2f} {r.opp_manager}", axis=1
    )
    return df


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    games = head_to_head(weeks)
    cols = ["season", "week", "manager", "points", "opp_manager", "opp_points", "is_playoff"]

    unlucky = games[games.lost].nlargest(10, "points")
    lucky = games[games.won].nsmallest(10, "points")
    nail = games[games.margin > 0].nsmallest(10, "margin")
    blowouts = games.nlargest(10, "margin")

    return {
        "all_play": all_play(arc, weeks),
        "unlucky_losses": rows(unlucky, cols),
        "lucky_wins": rows(lucky, cols),
        "nail_biters": rows(nail, [*cols, "margin"]),
        "blowouts": rows(blowouts, [*cols, "margin"]),
    }
