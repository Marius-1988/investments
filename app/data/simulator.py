"""Simulador de mercado con cambios de régimen y shocks.

Sirve para probar a los agentes sin dinero real y fuera de horario.
Cada step() genera una vela de 1 minuto (tiempo acelerado).
"""
from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Tuple

from ..config import Instrument
from ..models import Bar, Quote
from .base import MarketDataFeed

REGIMES = {
    #            drift/min  vol mult  spread mult
    "CALM":       (0.00000, 0.8, 1.0),
    "TREND_UP":   (0.00060, 1.0, 1.0),
    "TREND_DOWN": (-0.00060, 1.1, 1.2),
    "VOLATILE":   (0.00000, 2.2, 1.8),
    "SHOCK":      (0.00000, 4.0, 3.0),
}

TRANSITIONS = {
    "CALM":       {"CALM": 0.93, "TREND_UP": 0.03, "TREND_DOWN": 0.02, "VOLATILE": 0.015, "SHOCK": 0.005},
    "TREND_UP":   {"TREND_UP": 0.92, "CALM": 0.05, "VOLATILE": 0.02, "TREND_DOWN": 0.01},
    "TREND_DOWN": {"TREND_DOWN": 0.90, "CALM": 0.06, "VOLATILE": 0.03, "SHOCK": 0.01},
    "VOLATILE":   {"VOLATILE": 0.85, "CALM": 0.10, "TREND_DOWN": 0.03, "SHOCK": 0.02},
    "SHOCK":      {"VOLATILE": 0.70, "SHOCK": 0.20, "TREND_DOWN": 0.10},
}

BETA = {"LOW": 0.4, "MEDIUM": 1.0, "HIGH": 1.4}
BASE_SPREAD = {"LOW": 0.0010, "MEDIUM": 0.0020, "HIGH": 0.0035}


class SimulatedFeed(MarketDataFeed):
    name = "simulator"
    accelerated = True

    def __init__(self, universe: List[Instrument], seed: Optional[int] = None):
        self.universe = {i.symbol: i for i in universe}
        self.rng = random.Random(seed)
        self.price: Dict[str, float] = {s: i.sim_price for s, i in self.universe.items()}
        self.micro_drift: Dict[str, float] = {s: 0.0 for s in self.universe}
        self.regime = "CALM"
        self.sim_clock = time.time() - 120 * 60

    def _next_regime(self) -> None:
        r, acc = self.rng.random(), 0.0
        for nxt, p in TRANSITIONS[self.regime].items():
            acc += p
            if r <= acc:
                self.regime = nxt
                return

    def _bar(self) -> Tuple[Dict[str, Bar], Dict[str, Quote]]:
        self._next_regime()
        drift, vmult, smult = REGIMES[self.regime]
        mkt = drift + self.rng.gauss(0, 0.0012 * vmult)
        if self.regime == "SHOCK":
            mkt += self.rng.choice([-1, 1]) * self.rng.uniform(0.006, 0.02)
        self.sim_clock += 60
        bars, quotes = {}, {}
        for s, inst in self.universe.items():
            risk = inst.static_risk
            # micro-tendencia idiosincrática (AR(1)) -> genera oportunidades de momentum de corto plazo
            self.micro_drift[s] = 0.85 * self.micro_drift[s] + self.rng.gauss(0, inst.sim_vol * 0.25)
            idio = self.micro_drift[s] + self.rng.gauss(0, inst.sim_vol * vmult * 0.8)
            ret = BETA[risk] * mkt + idio
            o = self.price[s]
            c = max(0.01, o * (1 + ret))
            wick = abs(self.rng.gauss(0, inst.sim_vol * vmult * 0.6))
            h = max(o, c) * (1 + wick)
            l = min(o, c) * (1 - wick)
            vol = math.exp(self.rng.gauss(8, 0.6)) * vmult
            self.price[s] = c
            bars[s] = Bar(self.sim_clock, o, h, l, c, vol)
            half = c * BASE_SPREAD[risk] * smult * self.rng.uniform(0.7, 1.3) / 2
            quotes[s] = Quote(s, bid=round(c - half, 4), ask=round(c + half, 4), last=c, volume=vol, ts=self.sim_clock)
        return bars, quotes

    async def connect(self, symbols: List[str]) -> Dict[str, List[Bar]]:
        hist: Dict[str, List[Bar]] = {s: [] for s in self.universe}
        for _ in range(90):
            bars, _ = self._bar()
            for s, b in bars.items():
                hist[s].append(b)
        self.regime = "CALM"
        return hist

    async def step(self) -> Tuple[Dict[str, Quote], Optional[Dict[str, Bar]]]:
        bars, quotes = self._bar()
        return quotes, bars
