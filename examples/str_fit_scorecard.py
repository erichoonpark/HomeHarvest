"""
Backward-compatible wrapper.

Use `examples/str_suitability_filters.py` as the canonical STR suitability filter.
"""

from str_suitability_filters import *  # noqa: F401,F403
from str_suitability_filters import main


if __name__ == "__main__":
    main()
