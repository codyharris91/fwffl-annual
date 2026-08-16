"""Category 9 — the median game.

From 2022 the league plays two games a week: your opponent, and the league
median. It is the format's best idea, because it puts a floor under bad luck —
you can lose to the highest score of the week and still bank a win for being
good.

Sleeper encodes the result of both games in each roster's `record` string, two
characters per week, interleaved [head-to-head, median]. That string is what
`tests/test_median.py` checks the numbers here against: all 54 manager-seasons
reproduce exactly, so the median results below are Sleeper's own, not a guess at
how it rounds a 12-team median.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head, regular_season

PLAYOFF_CUTOFF = 6


def _median_weeks(arc: Archive, weeks: pd.DataFrame) -> pd.DataFrame:
    """Regular-season weeks from seasons that actually play a median game."""
    regular = regular_season(weeks, arc)
    using = {s.year for s in arc.completed if s.uses_median_match}
    return regular[regular.season.isin(using) & (regular.points > 0)].copy()


def records(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Career record against the median, beside the record against opponents."""
    frame = _median_weeks(arc, weeks)
    frame["beat_median"] = frame.points > frame["median"]

    grouped = frame.groupby("uid").agg(
        weeks=("beat_median", "size"),
        median_wins=("beat_median", "sum"),
        h2h_wins=("won", "sum"),
        h2h_losses=("lost", "sum"),
    )

    out = []
    for uid, r in grouped.iterrows():
        median_pct = r.median_wins / r.weeks * 100
        h2h_games = r.h2h_wins + r.h2h_losses
        h2h_pct = r.h2h_wins / h2h_games * 100 if h2h_games else 0.0
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "weeks": int(r.weeks),
                "median_wins": int(r.median_wins),
                "median_losses": int(r.weeks - r.median_wins),
                "median_pct": round(median_pct, 1),
                "h2h_wins": int(r.h2h_wins),
                "h2h_losses": int(r.h2h_losses),
                "h2h_pct": round(h2h_pct, 1),
                # Positive means they scored better than their matchups showed —
                # the median game handed back wins the schedule had taken.
                "rescue": round(median_pct - h2h_pct, 1),
            }
        )
    out.sort(key=lambda d: -d["median_pct"])
    return out


def double_weeks(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Weeks swept 2-0, and weeks lost 0-2."""
    frame = _median_weeks(arc, weeks)
    frame = frame[frame.opp_points.notna()]
    frame["beat_median"] = frame.points > frame["median"]

    grouped = frame.groupby("uid").apply(
        lambda g: pd.Series(
            {
                "weeks": len(g),
                "swept": int((g.won & g.beat_median).sum()),
                "wiped": int((g.lost & ~g.beat_median).sum()),
                "rescued": int((g.lost & g.beat_median).sum()),
                "flattered": int((g.won & ~g.beat_median).sum()),
            }
        ),
        include_groups=False,
    )

    out = []
    for uid, r in grouped.iterrows():
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "weeks": int(r.weeks),
                "swept": int(r.swept),
                "wiped": int(r.wiped),
                # Lost the matchup but still banked a median win.
                "rescued": int(r.rescued),
                # Won the matchup despite a below-median score.
                "flattered": int(r.flattered),
                "sweep_rate": round(r.swept / r.weeks * 100, 1) if r.weeks else 0.0,
            }
        )
    out.sort(key=lambda d: -d["swept"])
    return out


def near_misses(arc: Archive, weeks: pd.DataFrame, limit: int = 8) -> dict[str, Any]:
    """The weeks decided by a hair against the median line."""
    frame = _median_weeks(arc, weeks)
    frame["distance"] = (frame.points - frame["median"]).round(2)

    def rows(sub: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "season": r.season,
                "week": int(r.week),
                "manager": r.manager,
                "points": round(r.points, 2),
                "median": round(r._asdict()["median"], 2),
                "distance": round(r.distance, 2),
            }
            for r in sub.itertuples()
        ]

    below = frame[frame.distance < 0].nlargest(limit, "distance")
    above = frame[frame.distance > 0].nsmallest(limit, "distance")
    return {"just_missed": rows(below), "just_made_it": rows(above)}


def median_line(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """How high the bar has sat, season by season."""
    frame = _median_weeks(arc, weeks)
    out = []
    for season, group in frame.groupby("season"):
        weekly = group.groupby("week")["median"].first()
        out.append(
            {
                "season": season,
                "average": round(float(weekly.mean()), 1),
                "low": round(float(weekly.min()), 2),
                "high": round(float(weekly.max()), 2),
                "teams": arc.by_year[season].teams,
            }
        )
    out.sort(key=lambda d: d["season"])
    return out


def consistency(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Who lives closest to the median line — the most reliably average teams."""
    frame = _median_weeks(arc, weeks)
    frame["distance"] = frame.points - frame["median"]
    grouped = frame.groupby("uid").distance.agg(["mean", "std", "size"])
    out = [
        {
            "uid": uid,
            "manager": arc.manager(uid),
            "average_margin": round(r["mean"], 1),
            "spread": round(r["std"], 1),
            "weeks": int(r["size"]),
        }
        for uid, r in grouped.iterrows()
    ]
    out.sort(key=lambda d: -d["average_margin"])
    return out


def standings_impact(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """What the median game changed — who it made, and who it broke.

    Seeds are recomputed from head-to-head results alone and compared with the
    official standings, so the cost of the format is shown rather than asserted.
    """
    games = head_to_head(regular_season(weeks, arc))
    out = []

    for season in arc.completed:
        if not season.uses_median_match:
            continue

        mine = games[games.season == season.year]
        h2h = mine.groupby("uid").agg(wins=("won", "sum"), points=("points", "sum"))
        h2h_order = h2h.sort_values(["wins", "points"], ascending=False).index.tolist()

        official = []
        for r in season.rosters:
            uid = r.get("owner_id")
            settings = r["settings"]
            official.append(
                (uid, settings["wins"], settings["fpts"] + settings.get("fpts_decimal", 0) / 100)
            )
        official.sort(key=lambda t: (-t[1], -t[2]))
        official_order = [uid for uid, _, _ in official]

        moves = []
        for uid in official_order:
            if uid not in h2h.index:
                continue
            official_seed = official_order.index(uid) + 1
            h2h_seed = h2h_order.index(uid) + 1
            if official_seed == h2h_seed:
                continue
            moves.append(
                {
                    "uid": uid,
                    "manager": arc.manager(uid),
                    "h2h_seed": h2h_seed,
                    "official_seed": official_seed,
                    "change": h2h_seed - official_seed,
                    "made_playoffs": official_seed <= PLAYOFF_CUTOFF,
                    "would_have": h2h_seed <= PLAYOFF_CUTOFF,
                }
            )
        moves.sort(key=lambda d: -abs(d["change"]))
        flips = [m for m in moves if m["made_playoffs"] != m["would_have"]]
        out.append({"season": season.year, "moves": moves, "flips": flips})
    return out


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    seasons = [s.year for s in arc.completed if s.uses_median_match]
    return {
        "seasons": seasons,
        "first_season": seasons[0] if seasons else None,
        "records": records(arc, weeks),
        "double_weeks": double_weeks(arc, weeks),
        "near_misses": near_misses(arc, weeks),
        "line": median_line(arc, weeks),
        "consistency": consistency(arc, weeks),
        "impact": standings_impact(arc, weeks),
    }
