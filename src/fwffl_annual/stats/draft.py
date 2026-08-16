"""Category 5 — the draft: steals, busts, slots, and each manager's habits.

Judging a pick needs a baseline, and two obvious ones are both wrong.

Ranking a player's finish against every NFL player punishes injuries absurdly —
a round-one back who tears an ACL "finishes" 400th. But comparing a pick to the
average pick at that slot is wrong too: quarterbacks outscore every other
position in raw points here, so a position-blind baseline declares every late QB
a genius pick and buries everything else.

So value is measured against what *that position* normally returns at *that
slot*: a 17th-round quarterback is judged against other 17th-round quarterbacks.
Beating it is a steal, falling short is a bust.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from ..archive import SCORING_POSITIONS, Archive
from ._common import pick_label, rows

# Half-width of the smoothing window over pick number. Positional curves are
# thin — a few dozen picks spread over 200 slots — so they need a wide window.
SMOOTHING = 10
POSITION_SMOOTHING = 24

# Below this many picks a position cannot support its own curve (K and DEF in
# the early rounds, mostly) and falls back to the position-blind one.
MIN_POSITION_PICKS = 20


def _curve(series: pd.Series, last_pick: int, window: int) -> pd.Series:
    """Smooth a per-pick average into a monotone-ish expectation curve."""
    full = series.reindex(range(1, last_pick + 1))
    return full.rolling(window * 2 + 1, center=True, min_periods=1).mean().ffill().bfill()


def expected_curve(picks: pd.DataFrame) -> pd.Series:
    """Average points returned by each overall pick number, smoothed."""
    last = int(picks["pick"].max())
    return _curve(picks.groupby("pick").points.mean().sort_index(), last, SMOOTHING)


def positional_curves(picks: pd.DataFrame) -> dict[str, pd.Series]:
    """One expectation curve per position, so like is compared with like."""
    last = int(picks["pick"].max())
    out: dict[str, pd.Series] = {}
    for position, group in picks.groupby("position"):
        if len(group) < MIN_POSITION_PICKS:
            continue
        out[position] = _curve(
            group.groupby("pick").points.mean().sort_index(), last, POSITION_SMOOTHING
        )
    return out


def with_value(picks: pd.DataFrame) -> pd.DataFrame:
    """Attach expected points and value-over-expected to every pick."""
    overall = expected_curve(picks)
    by_position = positional_curves(picks)

    expected = []
    for r in picks.itertuples():
        curve = by_position.get(r.position)
        value = curve.get(r.pick) if curve is not None else None
        if value is None or pd.isna(value):
            value = overall.get(r.pick)
        expected.append(round(float(value), 1))

    out = picks.copy()
    out["expected"] = expected
    out["value"] = (out.points - out.expected).round(1)
    out["label"] = [pick_label(p, t) for p, t in zip(out["pick"], out.teams, strict=True)]
    return out


def manager_grades(arc: Archive, picks: pd.DataFrame) -> list[dict[str, Any]]:
    """Total value added over expectation, per manager."""
    grouped = picks.groupby("uid").agg(
        picks=("value", "size"), total=("value", "sum"), average=("value", "mean")
    )
    early = picks[picks["round"] <= 5].groupby("uid").value.mean()
    out = []
    for uid, r in grouped.iterrows():
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "picks": int(r.picks),
                "total_value": round(r.total, 1),
                "value_per_pick": round(r.average, 1),
                "early_value": round(early.get(uid, 0.0), 1),
            }
        )
    out.sort(key=lambda d: -d["value_per_pick"])
    return out


def draft_dna(arc: Archive, picks: pd.DataFrame) -> list[dict[str, Any]]:
    """Each manager's revealed habits: first-round position, positional mix."""
    out = []
    for uid, group in picks.groupby("uid"):
        first_round = group[group["round"] == 1]
        early = group[group["round"] <= 5]
        first_pos = Counter(first_round.position)
        # Round in which they typically take their first QB — the loudest tell.
        qb_rounds = [
            g[g.position == "QB"]["round"].min()
            for _, g in group.groupby("season")
            if not g[g.position == "QB"].empty
        ]
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "drafts": int(group.season.nunique()),
                "first_round": dict(first_pos),
                "favourite_first": first_pos.most_common(1)[0][0] if first_pos else None,
                "early_mix": {
                    pos: round(n / len(early) * 100)
                    for pos, n in Counter(early.position).most_common()
                },
                "first_qb_round": round(sum(qb_rounds) / len(qb_rounds), 1) if qb_rounds else None,
            }
        )
    out.sort(key=lambda d: -d["drafts"])
    return out


def undrafted_gems(arc: Archive, picks: pd.DataFrame, totals: dict[str, dict[str, float]],
                   players: pd.DataFrame) -> list[dict[str, Any]]:
    """The best player nobody drafted, each season — and who scooped them."""
    out = []
    for season in arc.completed:
        year = season.year
        drafted = set(picks[picks.season == year].pid)
        scored = {
            pid: pts
            for pid, pts in totals.get(year, {}).items()
            if arc.position(pid) in SCORING_POSITIONS
        }
        ranked = sorted(scored.items(), key=lambda kv: -kv[1])
        rank = {pid: i + 1 for i, (pid, _) in enumerate(ranked)}

        held = players[(players.season == year)]
        for pid, pts in ranked:
            if pid in drafted:
                continue
            owners = held[held.pid == pid]
            top_owner = (
                owners.groupby("manager").points.sum().idxmax() if not owners.empty else None
            )
            out.append(
                {
                    "season": year,
                    "player": arc.player_name(pid),
                    "position": arc.position(pid),
                    "points": round(pts, 1),
                    "overall_finish": rank[pid],
                    "claimed_by": top_owner,
                    "weeks_rostered": int(owners.week.nunique()) if not owners.empty else 0,
                }
            )
            break
    return out


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    picks = with_value(tables["picks"])
    cols = ["season", "label", "pick", "manager", "player", "position", "points",
            "expected", "value", "position_rank"]

    first_overall = picks[picks["pick"] == 1].sort_values("season")
    slots = picks.groupby(["season", "slot"]).agg(uid=("uid", "first")).reset_index()
    champions = {s.year: s.champion for s in arc.completed}
    slots["champion"] = [
        champions.get(r.season) == r.uid for r in slots.itertuples()
    ]
    slot_table = (
        slots.groupby("slot").agg(drafts=("champion", "size"), titles=("champion", "sum"))
        .reset_index()
    )

    return {
        "steals": rows(picks[picks["round"] >= 5].nlargest(12, "value"), cols),
        "busts": rows(picks[picks["round"] <= 4].nsmallest(12, "value"), cols),
        "first_overall": rows(
            first_overall, ["season", "manager", "player", "position", "points", "value", "position_rank"]
        ),
        "grades": manager_grades(arc, picks),
        "dna": draft_dna(arc, picks),
        "slots": slot_table.to_dict("records"),
        "undrafted": undrafted_gems(arc, picks, tables["season_totals"], tables["player_weeks"]),
    }
