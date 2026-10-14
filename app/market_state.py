"""Estado de mercado compartido: velas, cotizaciones, índice sintético y spreads."""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from .models import Bar, Quote


class MarketState:
    def __init__(self, symbols: List[str], maxlen: int = 400):
        self.symbols = symbols
        self.bars: Dict[str, Deque[Bar]] = {s: deque(maxlen=maxlen) for s in symbols}
        self.quotes: Dict[str, Quote] = {}
        self.index: Deque[float] = deque(maxlen=maxlen)       # índice equiponderado (proxy Merval)
        self.spreads: Dict[str, Deque[float]] = {s: deque(maxlen=120) for s in symbols}
        self.base: Dict[str, float] = {}
        self.minute = 0                                        # contador de velas cerradas (reloj del sistema)

    def _index_point(self) -> Optional[float]:
        vals = []
        for s in self.symbols:
            if self.bars[s]:
                if s not in self.base:
                    self.base[s] = self.bars[s][0].close
                vals.append(self.bars[s][-1].close / self.base[s])
        return 1000 * sum(vals) / len(vals) if vals else None

    def load_history(self, hist: Dict[str, List[Bar]]) -> None:
        n = max((len(v) for v in hist.values()), default=0)
        for s, bars in hist.items():
            if s in self.bars and bars:
                self.base.setdefault(s, bars[0].close)
        for i in range(n):
            for s, bars in hist.items():
                if s in self.bars and i < len(bars):
                    self.bars[s].append(bars[i])
            p = self._index_point()
            if p:
                self.index.append(p)

    def update(self, quotes: Dict[str, Quote], closed: Optional[Dict[str, Bar]]) -> bool:
        self.quotes.update(quotes)
        for s, q in quotes.items():
            if s in self.spreads:
                self.spreads[s].append(q.spread_pct)
        if not closed:
            return False
        for s, b in closed.items():
            if s in self.bars:
                self.bars[s].append(b)
        p = self._index_point()
        if p:
            self.index.append(p)
        self.minute += 1
        return True

    def closes(self, s: str) -> List[float]:
        return [b.close for b in self.bars[s]]
