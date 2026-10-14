"""Fuentes de datos de mercado."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from ..models import Bar, Quote


class MarketDataFeed(ABC):
    name: str = "base"
    # True: cada step() equivale a 1 vela de 1 minuto (simulación acelerada)
    accelerated: bool = False

    @abstractmethod
    async def connect(self, symbols: List[str]) -> Dict[str, List[Bar]]:
        """Conecta y devuelve historial inicial (velas de 1 minuto) por símbolo."""

    @abstractmethod
    async def step(self) -> Tuple[Dict[str, Quote], Optional[Dict[str, Bar]]]:
        """Devuelve cotizaciones actuales y, si cerró una vela, las velas cerradas."""
