"""Pure decision rules for checks: easy to unit-test and to explain to judges."""

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def classify_deviation(observed, center, scale, warn_z=3.0, fail_z=5.0, min_rel=0.25):
    """Alert only when a change is both statistically unusual (z-score) and big
    enough to matter (relative change). Either alone causes noisy alerts."""
    if observed is None or center is None or scale is None:
        return PASS, None
    dev = observed - center
    z = dev / scale
    rel = abs(dev) / max(abs(center), 1e-9)
    if abs(z) >= fail_z and rel >= min_rel:
        return FAIL, z
    if abs(z) >= warn_z and rel >= min_rel / 2:
        return WARN, z
    return PASS, z


def classify_rate_increase(rate, baseline_rate, warn_delta, fail_delta):
    """For rates where only an increase is bad (nulls, duplicates, invalid rows)."""
    delta = rate - (baseline_rate or 0.0)
    if delta >= fail_delta:
        return FAIL
    if delta >= warn_delta:
        return WARN
    return PASS


def is_dropped_column(null_rate, baseline_null_rate):
    """A column that is normally filled but arrives completely empty."""
    return null_rate >= 0.99 and (baseline_null_rate or 0.0) < 0.5
