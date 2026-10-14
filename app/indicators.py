"""Indicadores técnicos en Python puro (sin dependencias pesadas)."""
from __future__ import annotations

import math
from typing import List, Sequence

from .models import Bar


def ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes: Sequence[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    window = closes[-(period + 1):]
    for a, b in zip(window[:-1], window[1:]):
        d = b - a
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs: List[float] = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    trs = trs[-period:]
    return sum(trs) / len(trs)


def returns(closes: Sequence[float]) -> List[float]:
    return [(b / a - 1) for a, b in zip(closes[:-1], closes[1:]) if a]


def stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def vwap(bars: Sequence[Bar]) -> float:
    pv = sum(((b.high + b.low + b.close) / 3) * b.volume for b in bars)
    v = sum(b.volume for b in bars)
    return pv / v if v else (bars[-1].close if bars else 0.0)


def zscore(value: float, sample: Sequence[float]) -> float:
    sd = stdev(sample)
    if sd == 0:
        return 0.0
    m = sum(sample) / len(sample)
    return (value - m) / sd
