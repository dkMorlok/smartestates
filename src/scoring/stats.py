"""Statistics over a segment's listings: price-per-m² distribution.

Pure functions over lists of numbers — no DB, no ORM. The materialise task
calls these with the listings it loaded.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal


def ppm2(price: Decimal | float | int | None, size: Decimal | float | int | None) -> float | None:
    """Compute price per m². Returns None on missing/zero inputs."""
    if price is None or size is None:
        return None
    try:
        p = float(price)
        s = float(size)
    except (TypeError, ValueError):
        return None
    if p <= 0 or s <= 0:
        return None
    return p / s


@dataclass(frozen=True)
class PpmStats:
    """Summary stats over a segment's ppm² values."""

    n_samples: int
    median: float
    trimmed_mean: float
    p25: float
    p75: float
    stddev: float

    def is_usable(self, min_samples: int = 30) -> bool:
        return self.n_samples >= min_samples


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile, assuming `sorted_values` is non-empty + sorted."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def compute_ppm2_stats(values: list[float], *, trim_pct: float = 0.10) -> PpmStats | None:
    """Compute median / trimmed-mean / quartiles over a list of ppm² values.

    `trim_pct` defines a symmetric trim (e.g. 0.10 drops the top and bottom
    10% before averaging) to keep outlier listings from dragging the mean.

    Returns None when there's not even one usable value to summarise.
    """
    cleaned = [v for v in values if v is not None and math.isfinite(v) and v > 0]
    if not cleaned:
        return None
    cleaned.sort()
    n = len(cleaned)

    trim_n = int(n * trim_pct)
    trimmed_window = cleaned[trim_n : n - trim_n] if n - 2 * trim_n > 0 else cleaned

    stddev = float(statistics.pstdev(cleaned)) if n > 1 else 0.0

    return PpmStats(
        n_samples=n,
        median=float(statistics.median(cleaned)),
        trimmed_mean=float(sum(trimmed_window) / len(trimmed_window)),
        p25=float(_quantile(cleaned, 0.25)),
        p75=float(_quantile(cleaned, 0.75)),
        stddev=stddev,
    )
