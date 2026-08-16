# FWFFL Annual

Six seasons of a Sleeper fantasy football league, rebuilt from the API into a
single-page record book.

```bash
uv run fwffl-annual        # fetch, compute, render
open data/fwffl-annual.html
```

The league is discovered by walking Sleeper's `previous_league_id` chain back
from the current season, so adding next year requires changing nothing.

## What it reads

Everything the Sleeper API will give up about the league — 972 team-weeks, 16,048
rostered player-weeks, 858 draft picks and 2,019 transactions across five
completed seasons, plus full NFL season stat lines so players nobody rostered can
still be scored.

Not available from the API, and therefore not here: league chat, and per-pick
draft timestamps.

## Layout

```
src/fwffl_annual/
  sleeper.py     HTTP adapter + disk cache. No business logic.
  archive.py     Walks the league chain; season objects and identity maps.
  scoring.py     Stat line + scoring settings -> points. Pure.
  frames.py      Four tidy tables everything downstream reads.
  stats/         One module per chapter of the page.
  build.py       -> data/annual.json
  render.py      -> data/fwffl-annual.html
templates/       Jinja page + stylesheet
```

`build` and `render` are deliberately separate: the numbers can be inspected,
diffed between runs, and tested without going near HTML.

## Three decisions worth knowing

Most of the work here was picking baselines that don't lie.

**Scoring.** Every player is scored under the league's own settings rather than a
public half-PPR board — first downs, a TE reception bonus, and 5-point passing
touchdowns move players a long way. This reproduces Sleeper's published totals
exactly, which `tests/test_scoring.py` asserts against every player rostered for a
full season.

**Luck.** The all-play record uses regular-season weeks only. Sleeper still scores
the six eliminated teams during the playoffs, and those teams are not trying —
counting them flatters everyone still alive.

**Draft value.** Ranking a player's finish against the whole league punishes
injuries absurdly (a round-one back who tears an ACL "finishes" 400th). But
comparing a pick to the average pick at that slot is also wrong: quarterbacks
outscore every other position in raw points, so a position-blind baseline
declares every late QB a genius and buries everything else. Each pick is measured
against its own position at its own slot.

Head-to-head records exclude the weekly median game; the official standings
include it. Both appear on the page, labelled.

## Caching

Responses land in `data/cache/` and completed seasons are treated as immutable.
The cache is gitignored; a cold run refetches in about 20 seconds. If the network
fails and a cached copy exists, the stale copy is served rather than failing the
run.

## Tests

```bash
uv run pytest
```

They run against the real cached archive rather than fixtures, so they catch
upstream data changes as well as regressions.
