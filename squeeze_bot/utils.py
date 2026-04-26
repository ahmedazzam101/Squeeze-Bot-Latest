from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_linear(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp(((value - low) / (high - low)) * 100)
