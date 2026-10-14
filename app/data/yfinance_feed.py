"""Feed de Yahoo Finance (tickers BYMA con sufijo .BA). Datos con demora: SOLO para paper trading."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Tuple

from ..models import Bar, Quote
from .base import MarketDataFeed

ASSUMED_SPREAD = 0.002


class YFinanceFeed(MarketDataFeed):
    name = "yfinance"
    accelerated = False

    def __init__(self, poll_seconds: int = 60):
        self.poll_seconds = poll_seconds
        self.symbols: List[str] = []
        self.last_fetch = 0.0
        self.last_bar_ts: Dict[str, float] = {}
        self.quotes: Dict[str, Quote] = {}

    def _download(self) -> Dict[str, List[Bar]]:
        import yfinance as yf  # import diferido: dependencia opcional

        tickers = " ".join(f"{s}.BA" for s in self.symbols)
        df = yf.download(tickers=tickers, period="1d", interval="1m", group_by="ticker",
                         progress=False, auto_adjust=False, threads=True)
        out: Dict[str, List[Bar]] = {}
        for s in self.symbols:
            try:
                sub = df[f"{s}.BA"].dropna() if len(self.symbols) > 1 else df.dropna()
            except KeyError:
                continue
            out[s] = [Bar(ts.timestamp(), float(r["Open"]), float(r["High"]), float(r["Low"]),
                          float(r["Close"]), float(r["Volume"])) for ts, r in sub.iterrows()]
        return out

    async def connect(self, symbols: List[str]) -> Dict[str, List[Bar]]:
        self.symbols = symbols
        hist = await asyncio.to_thread(self._download)
        self.last_fetch = time.time()
        for s, bars in hist.items():
            if bars:
                self.last_bar_ts[s] = bars[-1].ts
                c = bars[-1].close
                self.quotes[s] = Quote(s, c * (1 - ASSUMED_SPREAD / 2), c * (1 + ASSUMED_SPREAD / 2), c, bars[-1].volume)
        return hist

    async def step(self) -> Tuple[Dict[str, Quote], Optional[Dict[str, Bar]]]:
        if time.time() - self.last_fetch < self.poll_seconds:
            return self.quotes, None
        hist = await asyncio.to_thread(self._download)
        self.last_fetch = time.time()
        new_bars: Dict[str, Bar] = {}
        for s, bars in hist.items():
            if not bars:
                continue
            b = bars[-1]
            if b.ts > self.last_bar_ts.get(s, 0):
                new_bars[s] = b
                self.last_bar_ts[s] = b.ts
            self.quotes[s] = Quote(s, b.close * (1 - ASSUMED_SPREAD / 2), b.close * (1 + ASSUMED_SPREAD / 2), b.close, b.volume)
        return self.quotes, (new_bars or None)
