"""Auto-import all source modules so they register themselves."""
from __future__ import annotations

# Import each source so its @register_source runs.
from scraper.sources import sreality  # noqa: F401
