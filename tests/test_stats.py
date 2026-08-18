"""Guards on the judgement calls — the places where a plausible-looking
implementation would produce a wrong-but-believable number."""

from __future__ import annotations

import pytest

from fwffl_annual.frames import optimal_lineup
from fwffl_annual.stats import build_all
from fwffl_annual.stats._common import head_to_head, regular_season
from fwffl_annual.stats.draft import positional_curves, with_value


# --- optimal lineup -------------------------------------------------------

def test_optimal_lineup_respects_slots():
    points = {"qb1": 30, "qb2": 25, "rb1": 20, "rb2": 15, "wr1": 10, "te1": 5}
    positions = {"qb1": "QB", "qb2": "QB", "rb1": "RB", "rb2": "RB", "wr1": "WR", "te1": "TE"}
    total, chosen = optimal_lineup(points, ["QB", "RB", "WR", "TE"], positions.get)
    assert total == 65  # only one QB may be used
    assert "qb2" not in chosen


def test_optimal_lineup_fills_flex_with_best_remaining():
    points = {"rb1": 20, "rb2": 18, "wr1": 9, "te1": 4}
    positions = {"rb1": "RB", "rb2": "RB", "wr1": "WR", "te1": "TE"}
    total, chosen = optimal_lineup(points, ["RB", "WR", "FLEX"], positions.get)
    # RB slot takes rb1, WR takes wr1, FLEX should take rb2 (18) over te1 (4).
    assert total == 47
    assert "rb2" in chosen


def test_optimal_lineup_never_scores_below_the_actual_lineup(tables):
    """A manager cannot beat the best possible lineup."""
    weeks = tables["team_weeks"]
    played = weeks[weeks.optimal > 0]
    assert (played.points <= played.optimal + 0.01).all()


# --- filters --------------------------------------------------------------

def test_head_to_head_excludes_weeks_with_no_opponent(tables):
    games = head_to_head(tables["team_weeks"])
    assert games.opp_points.notna().all()
    assert len(games) < len(tables["team_weeks"])


def test_regular_season_stops_before_the_playoffs(arc, tables):
    regular = regular_season(tables["team_weeks"], arc)
    for season in arc.completed:
        weeks = regular[regular.season == season.year].week
        assert weeks.max() == season.playoff_week - 1


# --- draft value ----------------------------------------------------------

def test_draft_value_baseline_is_positional(tables):
    """A position-blind baseline made every late QB look like a genius pick.

    The regression guard: quarterbacks must not dominate the steal list, since
    they out-score every other position in raw points here.
    """
    picks = with_value(tables["picks"])
    top_steals = picks.nlargest(12, "value")
    assert (top_steals.position == "QB").sum() < 8, "positional baseline is not applied"

    curves = positional_curves(tables["picks"])
    assert {"QB", "RB", "WR", "TE"} <= set(curves)
    # A first-round QB is expected to out-score a last-round QB.
    qb = curves["QB"]
    assert qb.iloc[0] > qb.iloc[-1]


def test_expected_value_is_zero_sum_ish(tables):
    """Value is measured against an average, so it should roughly cancel out."""
    picks = with_value(tables["picks"])
    assert picks.value.mean() == pytest.approx(0, abs=12)


# --- payload --------------------------------------------------------------

def test_every_category_produces_output(arc, tables):
    payload = build_all(arc, tables)
    assert set(payload) == {
        "ledger", "acquisition", "luck", "median", "records", "coaching", "draft",
        "waivers", "rivalries", "comedy",
    }
    for name, section in payload.items():
        assert section, f"{name} is empty"


def test_champions_are_recorded_for_every_completed_season(arc):
    for season in arc.completed:
        assert season.champion, f"{season.year} has no champion"
        assert season.runner_up
        assert season.champion != season.runner_up


def test_luck_is_actual_minus_all_play(arc, tables):
    payload = build_all(arc, tables)
    for row in payload["luck"]["all_play"]:
        assert row["luck"] == pytest.approx(row["actual_pct"] - row["all_play_pct"], abs=0.11)


def test_bidding_war_margin_is_never_negative(arc, tables):
    """A losing bid above the winning one means an over-budget rejection, and
    must be reported separately rather than as a negative margin."""
    payload = build_all(arc, tables)
    for war in payload["waivers"]["bidding_wars"]:
        if war["margin"] is not None:
            assert war["margin"] >= 0, war
        for loser in war["overbid_but_failed"]:
            assert loser["bid"] > war["winning_bid"]
