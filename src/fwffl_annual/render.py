"""Render the annual JSON into self-contained HTML pages.

Two pages, each emitted twice:

  annual.html.j2    the record book — records, luck, the median game, rivalries
  building.html.j2  where the points came from — draft, trades, the waiver wire

Each is written as a fragment for Claude Artifacts, which supplies its own
document skeleton, and as a complete document for GitHub Pages. The document is
built by splitting the fragment at `<main>`: everything above it is already
exactly the head content, so the two copies cannot drift apart.

Every output is one file with no external requests, so any of them can be served
from anywhere without an asset pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
DATA = ROOT / "data" / "annual.json"
OUTPUT = ROOT / "data" / "fwffl-annual.html"
SITE = ROOT / "docs" / "index.html"

BUILDING_OUTPUT = ROOT / "data" / "fwffl-building.html"
BUILDING_SITE = ROOT / "docs" / "building" / "index.html"
BUILDING_DESCRIPTION = (
    "Where every point in the league actually came from — the draft, a trade, or "
    "the waiver wire — and whether a bad draft can be survived."
)

# Shown when the link is pasted into a chat app. Worth having, since that is
# how a page like this actually gets passed around.
SOCIAL_DESCRIPTION = (
    "Six seasons of FWFFL, rebuilt from every box score, draft pick and waiver "
    "bid the league ever placed — including the ones that lost."
)


def _signed(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}"


def _record(string: str) -> list[str]:
    return list(string or "")


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["signed"] = _signed
    env.filters["record"] = _record
    return env


def scales(payload: dict[str, Any]) -> dict[str, float]:
    """Chart axis maxima, computed once so the template stays declarative."""
    volatility = payload["records"]["volatility"]
    return {
        "luck": max(abs(r["luck"]) for r in payload["luck"]["all_play"]),
        "draft_value": max(abs(r["value_per_pick"]) for r in payload["draft"]["grades"]),
        "split": max(abs(r["delta"]) for r in payload["records"]["splits"]),
        "ceiling": max(r["ceiling"] for r in volatility),
        "floor": min(r["floor"] for r in volatility),
        "bid": max(r["bid"] for r in payload["waivers"]["biggest_bids"]),
    }


def render(payload: dict[str, Any] | None = None, *, template: str = "annual.html.j2") -> str:
    payload = payload or json.loads(DATA.read_text())
    page = environment().get_template(template)
    # The stylesheet is read rather than {% include %}d so Jinja never parses CSS.
    css = Markup((TEMPLATES / "_style.css").read_text())
    return page.render(css=css, scales=scales(payload), **payload)


def standalone(fragment: str, *, description: str = SOCIAL_DESCRIPTION) -> str:
    """Wrap the artifact fragment in a real document for hosting.

    The template puts the title, viewport and stylesheet before `<main>`, which
    is exactly the head content — so splitting there needs no parsing, and the
    two outputs can never drift apart.
    """
    head, marker, body = fragment.partition("<main>")
    if not marker:
        raise ValueError("expected the rendered page to contain a <main> element")

    title = "The FWFFL Annual"
    if "<title>" in head:
        title = head.split("<title>", 1)[1].split("</title>", 1)[0]

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
{head.strip()}
<meta name="description" content="{description}">
<!-- Shareable by link, but kept out of search results: the page names real
     people. This meta tag is the lever that works here — a robots.txt inside a
     project site is ignored, because crawlers only read the one at the domain
     root, which belongs to the user site rather than this repo. -->
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta name="twitter:card" content="summary">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0b1013">
</head>
<body>
{marker}{body}
</body>
</html>
"""


def _emit(html: str, artifact: Path, site: Path, description: str) -> None:
    artifact.write_text(html)
    print(f"wrote {artifact} ({len(html) / 1024:.0f} KB)")

    site.parent.mkdir(parents=True, exist_ok=True)
    document = standalone(html, description=description)
    site.write_text(document)
    print(f"wrote {site} ({len(document) / 1024:.0f} KB)")


def main() -> None:
    payload = json.loads(DATA.read_text())

    _emit(render(payload), OUTPUT, SITE, SOCIAL_DESCRIPTION)
    _emit(
        render(payload, template="building.html.j2"),
        BUILDING_OUTPUT,
        BUILDING_SITE,
        BUILDING_DESCRIPTION,
    )
    # Stops GitHub Pages running the content through Jekyll.
    (SITE.parent / ".nojekyll").touch()


if __name__ == "__main__":
    main()
