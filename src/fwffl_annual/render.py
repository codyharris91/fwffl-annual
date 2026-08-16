"""Render the annual JSON into a single self-contained HTML page.

The page is written for Claude Artifacts, which wraps the file in its own
document skeleton — so the template emits a `<title>`, a `<style>`, and body
content, with no `<html>`/`<head>`/`<body>` of its own. Browsers open the file
directly just fine regardless.
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


def main() -> None:
    html = render()
    OUTPUT.write_text(html)
    print(f"wrote {OUTPUT} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
