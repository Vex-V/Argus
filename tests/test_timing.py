from datetime import datetime, timezone

from services.analyzers.timing.analyzer import (
    analyze_timing,
    bhattacharyya_coefficient,
    build_hour_histogram,
)


def _ts(hour: int, day_offset: int = 0) -> float:
    dt = datetime(2026, 1, 5 + day_offset, hour, 0, tzinfo=timezone.utc)
    return dt.timestamp()


def test_hour_histogram_normalizes_to_probability():
    hist = build_hour_histogram([_ts(9) for _ in range(10)])
    assert abs(hist.sum() - 1.0) < 1e-9
    assert hist[9] == 1.0


def test_bhattacharyya_identical_is_one():
    hist = build_hour_histogram([_ts(h) for h in range(8, 18)])
    assert abs(bhattacharyya_coefficient(hist, hist) - 1.0) < 1e-9


def test_same_hours_high_score():
    a = [_ts(h % 24, d) for d in range(3) for h in (9, 10, 11, 12, 13)]
    b = [_ts(h % 24, d) for d in range(3) for h in (9, 10, 11, 12, 13)]
    result = analyze_timing(a, b)
    assert result["combined_score"] > 0.7


def test_day_vs_night_low_score():
    day = [_ts(h, d) for d in range(3) for h in (9, 10, 11, 12, 13)]
    night = [_ts(h, d) for d in range(3) for h in (0, 1, 2, 3, 4)]
    result = analyze_timing(day, night)
    assert result["combined_score"] < 0.5


def test_insufficient_data_returns_zero():
    result = analyze_timing([_ts(9)], [_ts(9)])
    assert result["combined_score"] == 0.0
    assert "insufficient_data" in result["evidence"][0]
