"""Scoring v1: market segmentation, ppm² statistics, hedonic regression.

The pipeline (see docs/SCORING.md):
  1. Bucket every active listing into a `market_segment` by
     (city_district, disposition, ownership, building_type, size, condition).
  2. Compute ppm² stats per segment from the last 90 days of listings.
  3. Fit a per-(city, property_type, ownership_type) hedonic regression.
  4. For each listing: undervaluation = predicted ppm² - actual ppm²;
     attach risk flags, confidence, composite score.

Everything outside `worker.tasks.scoring` is pure functions over plain
types so the logic is unit-testable without a database.
"""
