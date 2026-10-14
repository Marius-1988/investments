"""Feed basado en cotizaciones del broker conectado: arma velas de 1 minuto a partir de ticks."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ..models import Bar, Quote
from .base import MarketDataFeed


class BrokerQuoteFeed(MarketDataFeed):
    name = "broker"
    accelerated = False

    def __init__(self, broker):
        self.broker = broker
        self.symbols: List[str] = []
        self.building: Dict[str, Bar] = {}
        self.current_minute = 0

    async def connect(self, symbols: List[str]) -> Dict[str, List[Bar]]:
        self.symbols = symbols
        self.current_minute = int(time.time() // 60)
        return {s: [] for s in symbols}   # sin historial: los agentes esperan el warm-up

    async def step(self) -> Tuple[Dict[str, Quote], Optional[Dict[str, Bar]]]:
        quotes = await self.broker.get_quotes(self.symbols)
        minute = int(time.time() // 60)
        closed: Dict[str, Bar] = {}
        if minute != self.current_minute:
            closed = dict(self.building)
            self.building.clear()
            self.current_minute = minute
        for s, q in quotes.items():
            px = q.last or q.mid
            if not px:
                continue
            b = self.building.get(s)
            if b is None:
                self.building[s] = Bar(minute * 60, px, px, px, px, q.volume)
            else:
                b.high, b.low, b.close = max(b.high, px), min(b.low, px), px
                b.volume = max(b.volume, q.volume)
        return quotes, (closed or None)
