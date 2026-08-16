"""Build the numbers, then render the page.

    uv run fwffl-annual

Both steps are also runnable on their own:

    uv run python -m fwffl_annual.build     # data/annual.json
    uv run python -m fwffl_annual.render    # data/fwffl-annual.html
"""

from __future__ import annotations

from . import build, render


def main() -> None:
    build.main()
    render.main()


if __name__ == "__main__":
    main()
