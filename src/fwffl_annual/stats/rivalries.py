"""Category 7 — rivalries and villains: who owns who, and which players haunt you."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head

MIN_MEETINGS = 5


def matrix(arc: Archive, weeks: pd.DataFrame) -> dict[str, Any]:
    """Full head-to-head grid, restricted to managers in the current league."""
    games = head_to_head(weeks)
    current = [u["user_id"] for u in arc.current.users]
    order = sorted(current, key=lambda uid: arc.manager(uid).lower())

    grid: dict[str, dict[str, dict[str, int]]] = {}
    for uid in order:
        row: dict[str, dict[str, int]] = {}
        mine = games[games.uid == uid]
        for other in order:
            if other == uid:
                continue
            head = mine[mine.opp_uid == other]
            if head.empty:
                continue
            row[other] = {"w": int(head.won.sum()), "l": int(head.lost.sum())}
        grid[uid] = row
    return {
        "managers": [{"uid": uid, "manager": arc.manager(uid)} for uid in order],
        "grid": grid,
    }


def lopsided(arc: Archive, weeks: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """The most one-sided matchups with enough meetings to mean something."""
    games = head_to_head(weeks)
    tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in games.itertuples():
        if r.won:
            tally[(r.uid, r.opp_uid)][0] += 1
        elif r.lost:
            tally[(r.uid, r.opp_uid)][1] += 1

    out = []
    for (uid, other), (wins, losses) in tally.items():
        total = wins + losses
        if total < MIN_MEETINGS or wins <= losses:
            continue
        out.append(
            {
                "manager": arc.manager(uid),
                "victim": arc.manager(other),
                "wins": wins,
                "losses": losses,
                "meetings": total,
                "margin": wins - losses,
            }
        )
    out.sort(key=lambda d: (-d["margin"], -d["meetings"]))
    return out[:limit]


def nemesis_players(arc: Archive, weeks: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """The player who has scored the most points *against* each manager."""
    lookup = {(r.season, r.week, r.roster_id): r for r in weeks.itertuples()}
    against: Counter[tuple[str, str]] = Counter()

    for r in weeks.itertuples():
        if pd.isna(r.opp_points) or r.opp_uid is None:
            continue
        opponent = lookup.get((r.season, r.week, r.opp_roster_id))
        if opponent is None:
            continue
        starters = json.loads(opponent.starters)
        points = json.loads(opponent.starter_points)
        for pid, value in zip(starters, points, strict=False):
            against[(r.uid, pid)] += float(value or 0)

    best: dict[str, tuple[str, float]] = {}
    for (uid, pid), total in against.items():
        if uid not in best or total > best[uid][1]:
            best[uid] = (pid, total)

    out = [
        {
            "uid": uid,
            "manager": arc.manager(uid),
            "player": arc.player_name(pid),
            "position": arc.position(pid),
            "points_against": round(total, 1),
        }
        for uid, (pid, total) in best.items()
    ]
    out.sort(key=lambda d: -d["points_against"])
    return out[:limit]


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    return {
        "matrix": matrix(arc, weeks),
        "lopsided": lopsided(arc, weeks),
        "nemesis": nemesis_players(arc, weeks),
    }
