"""
Backward-compatible wrapper.

Use `examples/scrape_listings_core.py` as the canonical core listings scraper.
"""

from scrape_listings_core import *  # noqa: F401,F403
from scrape_listings_core import main


if __name__ == "__main__":
    main()
