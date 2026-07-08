"""Posting-time pattern comparison (C11).

Builds 24-bin hour-of-day and 7-bin day-of-week probability distributions
from post timestamps and compares them with the Bhattacharyya coefficient
(1 = identical, 0 = no overlap). Combined 70% hourly / 30% weekly.
"""
from datetime import datetime, timezone

import numpy as np

_MIN_POSTS = 5
_HOURLY_WEIGHT = 0.7
_WEEKLY_WEIGHT = 0.3


def build_hour_histogram(timestamps: list[float]) -> np.ndarray:
    if not timestamps:
        return np.zeros(24)
    hours = [datetime.fromtimestamp(ts, tz=timezone.utc).hour for ts in timestamps]
    hist, _ = np.histogram(hours, bins=24, range=(0, 24))
    total = hist.sum()
    return (hist / total).astype(float) if total else hist.astype(float)


def build_dow_histogram(timestamps: list[float]) -> np.ndarray:
    if not timestamps:
        return np.zeros(7)
    days = [datetime.fromtimestamp(ts, tz=timezone.utc).weekday() for ts in timestamps]
    hist, _ = np.histogram(days, bins=7, range=(0, 7))
    total = hist.sum()
    return (hist / total).astype(float) if total else hist.astype(float)


def bhattacharyya_coefficient(p: np.ndarray, q: np.ndarray) -> float:
    """Bhattacharyya coefficient — overlap of two probability distributions."""
    return float(np.sum(np.sqrt(p * q)))


def analyze_timing(timestamps_a: list[float], timestamps_b: list[float]) -> dict:
    if len(timestamps_a) < _MIN_POSTS or len(timestamps_b) < _MIN_POSTS:
        return {
            "combined_score": 0.0,
            "evidence": [f"insufficient_data (need {_MIN_POSTS}+ posts each)"],
        }

    hour_a, hour_b = build_hour_histogram(timestamps_a), build_hour_histogram(timestamps_b)
    dow_a, dow_b = build_dow_histogram(timestamps_a), build_dow_histogram(timestamps_b)

    hourly_sim = bhattacharyya_coefficient(hour_a, hour_b)
    weekly_sim = bhattacharyya_coefficient(dow_a, dow_b)
    combined = _HOURLY_WEIGHT * hourly_sim + _WEEKLY_WEIGHT * weekly_sim

    peak_a = [int(h) for h in np.argsort(hour_a)[-3:][::-1]]
    peak_b = [int(h) for h in np.argsort(hour_b)[-3:][::-1]]
    shared_peaks = sorted(set(peak_a) & set(peak_b))

    evidence = [
        f"hourly_similarity: {hourly_sim:.3f}",
        f"weekly_similarity: {weekly_sim:.3f}",
        f"peak_hours_a: {peak_a}",
        f"peak_hours_b: {peak_b}",
    ]
    if shared_peaks:
        evidence.append(f"shared_peak_hours: {shared_peaks}")

    return {
        "hourly_similarity": round(hourly_sim, 4),
        "weekly_similarity": round(weekly_sim, 4),
        "combined_score": round(combined, 4),
        "evidence": evidence,
    }
