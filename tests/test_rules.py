from datetime import datetime

from trustlayer import rules
from trustlayer.baseline import hour_of_week
from trustlayer.robust import robust_center_scale


def test_robust_baseline_ignores_one_outage():
    normal = [100, 104, 98, 101, 99, 103, 97]
    center, scale = robust_center_scale(normal + [0])  # one hour the pipeline was down
    assert 98 <= center <= 101
    assert scale < 10


def test_robust_baseline_floor_for_flat_history():
    center, scale = robust_center_scale([50, 50, 50])
    assert center == 50
    assert scale == 2.5  # 5% of center, so tiny wobbles are not alerts


def test_robust_baseline_empty():
    assert robust_center_scale([None]) == (None, None)


def test_volume_drop_fails_but_normal_wobble_passes():
    assert rules.classify_deviation(600, 4000, 300)[0] == rules.FAIL
    assert rules.classify_deviation(4200, 4000, 300)[0] == rules.PASS


def test_statistically_odd_but_tiny_change_does_not_alert():
    # z = 10, but only a 1% change: not worth waking anyone up.
    assert rules.classify_deviation(1010, 1000, 1)[0] == rules.PASS


def test_unit_change_is_caught():
    # Amounts switched from dollars to cents.
    assert rules.classify_deviation(2800.0, 28.0, 2.0)[0] == rules.FAIL


def test_rate_increase_thresholds():
    assert rules.classify_rate_increase(0.05, 0.04, 0.10, 0.25) == rules.PASS
    assert rules.classify_rate_increase(0.20, 0.04, 0.10, 0.25) == rules.WARN
    assert rules.classify_rate_increase(0.64, 0.04, 0.10, 0.25) == rules.FAIL


def test_dropped_column_detection():
    assert rules.is_dropped_column(1.0, 0.0)
    assert not rules.is_dropped_column(1.0, 0.9)  # column is normally empty anyway
    assert not rules.is_dropped_column(0.5, 0.0)


def test_hour_of_week_matches_sql_convention():
    assert hour_of_week(datetime(2024, 1, 1, 0)) == 0  # Monday midnight
    assert hour_of_week(datetime(2024, 3, 4, 9)) == 9  # also a Monday
    assert hour_of_week(datetime(2024, 3, 10, 23)) == 167  # Sunday 23:00
