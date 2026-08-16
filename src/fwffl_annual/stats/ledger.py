"""Category 1 — the all-time ledger: records, titles, tenure, playoff history."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head


def all_time_record(arc: Archive, weeks: pd.DataFrame) -> list[dict[str, Any]]:
    """Career head-to-head record for every manager who has ever played."""
    games = head_to_head(weeks)
    grouped = games.groupby("uid").agg(
        games=("won", "size"),
        wins=("won", "sum"),
        losses=("lost", "sum"),
        ties=("tied", "sum"),
        points_for=("points", "sum"),
        points_against=("opp_points", "sum"),
        average=("points", "mean"),
        best=("points", "max"),
    )
    ring_count: dict[str, int] = {}
    for s in arc.completed:
        if s.champion:
            ring_count[s.champion] = ring_count.get(s.champion, 0) + 1

    out = []
    for uid, r in grouped.iterrows():
        seasons = arc.seasons_played.get(uid, [])
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "seasons": len([y for y in seasons if y in {s.year for s in arc.completed}]),
                "years": seasons,
                "games": int(r.games),
                "wins": int(r.wins),
                "losses": int(r.losses),
                "ties": int(r.ties),
                "win_pct": round(r.wins / r.games * 100, 1) if r.games else 0.0,
                "points_for": round(r.points_for, 1),
                "points_against": round(r.points_against, 1),
                "average": round(r.average, 2),
                "best": round(r.best, 2),
                "titles": ring_count.get(uid, 0),
                "active": uid in {u["user_id"] for u in arc.current.users},
            }
        )
    out.sort(key=lambda d: (-d["win_pct"], -d["games"]))
    return out


def season_results(arc: Archive) -> list[dict[str, Any]]:
    """Final standings for every completed season, straight from Sleeper."""
    out = []
    for s in arc.completed:
        table = []
        for r in s.rosters:
            settings = r["settings"]
            uid = r.get("owner_id")
            points = settings["fpts"] + settings.get("fpts_decimal", 0) / 100
            potential = settings.get("ppts", 0) + settings.get("ppts_decimal", 0) / 100
            table.append(
                {
                    "uid": uid,
                    "manager": arc.manager(uid),
                    "team_name": s.team_names.get(uid, ""),
                    "wins": settings["wins"],
                    "losses": settings["losses"],
                    "points_for": round(points, 2),
                    "points_against": round(
                        settings["fpts_against"] + settings.get("fpts_against_decimal", 0) / 100, 2
                    ),
                    "potential": round(potential, 2),
                    "efficiency": round(points / potential * 100, 1) if potential else None,
                    "record_string": (r.get("metadata") or {}).get("record", ""),
                    "made_playoffs": uid in s.playoff_teams,
                    "champion": uid == s.champion,
                    "runner_up": uid == s.runner_up,
                }
            )
        table.sort(key=lambda d: (-d["wins"], -d["points_for"]))
        out.append(
            {
                "year": s.year,
                "teams": s.teams,
                "champion": arc.manager(s.champion),
                "champion_uid": s.champion,
                "champion_team": s.team_names.get(s.champion, ""),
                "runner_up": arc.manager(s.runner_up),
                "median_match": s.uses_median_match,
                "standings": table,
            }
        )
    return out


def tenure(arc: Archive) -> dict[str, Any]:
    """Who has stayed, who passed through, and who is here for 2026."""
    completed = {s.year for s in arc.completed}
    current = {u["user_id"] for u in arc.current.users}
    people = []
    for uid, years in arc.seasons_played.items():
        played = [y for y in years if y in completed]
        people.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "years": years,
                "seasons_completed": len(played),
                "first": years[0],
                "last": years[-1],
                "active": uid in current,
                "titles": sum(1 for s in arc.completed if s.champion == uid),
            }
        )
    people.sort(key=lambda d: (-d["seasons_completed"], d["first"]))
    lifers = [p for p in people if len(p["years"]) == len(arc.seasons)]
    return {
        "everyone": people,
        "lifers": lifers,
        "departed": [p for p in people if not p["active"]],
        "newcomers": [p for p in people if p["years"] == [arc.current.year]],
    }


def playoff_history(arc: Archive) -> list[dict[str, Any]]:
    """Per-manager playoff appearances, plus the current drought."""
    completed = arc.completed
    out = []
    for uid in arc.seasons_played:
        appearances = [s.year for s in completed if uid in s.playoff_teams]
        eligible = [s.year for s in completed if uid in {u["user_id"] for u in s.users}]
        if not eligible:
            continue
        drought = 0
        for s in reversed(completed):
            if uid not in {u["user_id"] for u in s.users}:
                continue
            if uid in s.playoff_teams:
                break
            drought += 1
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "appearances": len(appearances),
                "eligible": len(eligible),
                "years": appearances,
                "rate": round(len(appearances) / len(eligible) * 100, 1),
                "drought": drought,
                "titles": sum(1 for s in completed if s.champion == uid),
                "finals": sum(1 for s in completed if uid in (s.champion, s.runner_up)),
            }
        )
    out.sort(key=lambda d: (-d["appearances"], -d["rate"]))
    return out


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    return {
        "all_time": all_time_record(arc, weeks),
        "seasons": season_results(arc),
        "tenure": tenure(arc),
        "playoffs": playoff_history(arc),
    }
