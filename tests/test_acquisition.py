"""Guards on the attribution engine.

Every claim on the roster-building page rests on one question — which door did
this point come through — so the invariants below are about that mapping being
total, exclusive, and honest about the difference between drafting well and
leaning on the draft.
"""

from __future__ import annotations

import pytest

from fwffl_annual.stats.acquisition import SOURCES, attribute, build


@pytest.fixture(scope="module")
def tagged(arc, tables):
    return attribute(arc, tables["team_weeks"])


@pytest.fixture(scope="module")
def payload(arc, tables):
    return build(arc, tables)


def test_every_rostered_player_week_is_attributed(arc, tables, tagged):
    """No point may arrive through a door we cannot name."""
    assert len(tagged) == len(tables["player_weeks"]), (
        "attribution dropped rows: some rostered player-weeks have no acquisition"
    )
    assert set(tagged.source.unique()) <= set(SOURCES)


def test_started_points_match_the_scoreboard(arc, tables, tagged):
    """Attributed starter points must reconcile with what teams actually scored."""
    attributed = tagged[tagged.started].points.sum()
    scored = tables["team_weeks"].points.sum()
    assert attributed == pytest.approx(scored, rel=0.001)


def test_channel_shares_sum_to_a_hundred(payload):
    assert sum(r["share"] for r in payload["channels"]["league"]) == pytest.approx(100, abs=0.2)
    for row in payload["channels"]["by_manager"]:
        assert sum(row[s] for s in SOURCES) == pytest.approx(100, abs=0.2)


def test_trades_are_two_sided_and_scored_from_the_winner_down(payload):
    for deal in payload["trades"]:
        assert len(deal["sides"]) == 2
        assert deal["sides"][0]["points"] >= deal["sides"][1]["points"]
        assert deal["margin"] >= 0


def test_trade_ledger_is_zero_sum(payload):
    """One side's gain is the other's surrender, so the league nets to nothing."""
    total = sum(row["net"] for row in payload["trade_ledger"])
    assert total == pytest.approx(0, abs=1.0)


def test_draft_quality_and_draft_reliance_are_different_measures(payload):
    """A manager can draft brilliantly and start almost none of it.

    If these two ranks were the same number, the page's central distinction
    would be fictional.
    """
    profiles = payload["profiles"]
    assert any(r["draft_rank"] != r["draft_value_rank"] for r in profiles)
    assert payload["currency"], "no manager ever traded a good draft away"
    for row in payload["currency"]:
        assert row["draft_rank"] - row["draft_value_rank"] >= 3


def test_dependence_buckets_cover_every_manager_season(payload):
    buckets = payload["dependence"]["buckets"]
    assert sum(b["teams"] for b in buckets) == len(payload["profiles"])
    assert sum(b["titles"] for b in buckets) == 5


def test_waiver_hits_are_ordered_and_priced(payload):
    best = payload["waivers"]["best"]
    assert best == sorted(best, key=lambda r: -r["points"])
    for row in payload["waivers"]["bargains"]:
        assert row["bid"] >= 25
        assert row["points_per_100"] == pytest.approx(row["points"] / row["bid"] * 100, abs=0.2)
