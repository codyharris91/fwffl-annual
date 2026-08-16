"""Sleeper writes both weekly results into each roster's `record` string, two
characters per week, interleaved [head-to-head, median]. That gives an exact
oracle for the median maths — including how Sleeper resolves the median of an
even number of teams — so this reconstructs the string and demands a match.
"""

from __future__ import annotations

import pytest

from fwffl_annual.stats.median import build


def _result_string(arc, weeks, season, uid: str) -> str:
    mine = weeks[
        (weeks.season == season.year) & (weeks.uid == uid) & (weeks.week < season.playoff_week)
    ].sort_values("week")
    head = ["W" if r.won else ("L" if r.lost else "T") for r in mine.itertuples()]
    med = ["W" if r.points > r._asdict()["median"] else "L" for r in mine.itertuples()]
    if season.uses_median_match:
        return "".join(a + b for a, b in zip(head, med, strict=True))
    return "".join(head)


def test_reconstructs_sleepers_record_string_exactly(arc, tables):
    weeks = tables["team_weeks"]
    checked = 0
    for season in arc.completed:
        for roster in season.rosters:
            uid = roster.get("owner_id")
            recorded = (roster.get("metadata") or {}).get("record", "")
            if not uid or not recorded:
                continue
            assert _result_string(arc, weeks, season, uid) == recorded, (
                f"{season.year} {arc.manager(uid)}"
            )
            checked += 1
    assert checked >= 50, f"only checked {checked} manager-seasons"


def test_median_only_covers_seasons_that_use_it(arc, tables):
    payload = build(arc, tables)
    expected = [s.year for s in arc.completed if s.uses_median_match]
    assert payload["seasons"] == expected
    assert "2021" not in payload["seasons"], "2021 had no median game"


def test_official_wins_equal_head_to_head_plus_median(arc, tables):
    """The two ledgers must add up to what Sleeper published."""
    payload = build(arc, tables)
    by_uid = {r["uid"]: r for r in payload["records"]}

    totals: dict[str, int] = {}
    for season in arc.completed:
        if not season.uses_median_match:
            continue
        for roster in season.rosters:
            uid = roster.get("owner_id")
            if uid:
                totals[uid] = totals.get(uid, 0) + roster["settings"]["wins"]

    for uid, official in totals.items():
        row = by_uid.get(uid)
        if row is None:
            continue
        assert row["h2h_wins"] + row["median_wins"] == official, arc.manager(uid)


def test_double_weeks_account_for_every_week(arc, tables):
    payload = build(arc, tables)
    for row in payload["double_weeks"]:
        total = row["swept"] + row["wiped"] + row["rescued"] + row["flattered"]
        assert total == row["weeks"], row["manager"]


def test_rescue_is_median_minus_head_to_head(arc, tables):
    payload = build(arc, tables)
    for row in payload["records"]:
        assert row["rescue"] == pytest.approx(row["median_pct"] - row["h2h_pct"], abs=0.11)


def test_standings_impact_reports_real_seed_moves(arc, tables):
    payload = build(arc, tables)
    assert payload["impact"], "no seasons analysed"
    for season in payload["impact"]:
        for move in season["moves"]:
            assert move["h2h_seed"] != move["official_seed"]
            assert move["change"] == move["h2h_seed"] - move["official_seed"]
        for flip in season["flips"]:
            assert flip["made_playoffs"] != flip["would_have"]
