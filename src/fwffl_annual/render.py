"""Render the annual JSON into a single self-contained HTML page.

Two outputs, one template:

  `data/fwffl-annual.html`  the fragment Claude Artifacts wants — it supplies its
                            own document skeleton, so the template emits only a
                            title, a stylesheet and content.
  `docs/index.html`         a complete document for GitHub Pages, built by moving
                            everything above `<main>` into a real `<head>`.

Both are one file with no external requests, so either can be served from
anywhere without an asset pipeline.
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


def render(payload: dict[str, Any] | None = None) -> str:
    payload = payload or json.loads(DATA.read_text())
    template = environment().get_template("annual.html.j2")
    # The stylesheet is read rather than {% include %}d so Jinja never parses CSS.
    css = Markup((TEMPLATES / "_style.css").read_text())
    return template.render(css=css, scales=scales(payload), **payload)


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


def main() -> None:
    html = render()
    OUTPUT.write_text(html)
    print(f"wrote {OUTPUT} ({len(html) / 1024:.0f} KB)")

    SITE.parent.mkdir(parents=True, exist_ok=True)
    site = standalone(html)
    SITE.write_text(site)
    # Stops GitHub Pages running the content through Jekyll.
    (SITE.parent / ".nojekyll").touch()
    print(f"wrote {SITE} ({len(site) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
