"""Robust statistics shared by Python and the Exasol UDF.

This file is pasted verbatim into the TRUSTLAYER.ROBUST_BASELINE Python UDF, so it
must stay dependency-free (standard library only) and define no run() function.
"""
import statistics

MAD_TO_SIGMA = 1.4826  # scales MAD to a standard deviation for normal data


def robust_center_scale(values):
    """Median and MAD-based sigma. One bad hour (holiday, outage) barely moves
    either, unlike mean and standard deviation."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None, None
    center = statistics.median(vals)
    mad = statistics.median([abs(v - center) for v in vals])
    scale = MAD_TO_SIGMA * mad
    # Floor so a perfectly steady history does not turn tiny wobbles into alerts.
    scale = max(scale, 0.05 * abs(center), 1e-9)
    return center, scale
