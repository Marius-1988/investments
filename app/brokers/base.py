"""Interfaz común de brokers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..models import Order, Quote


class BrokerError(Exception):
    pass


class Broker(ABC):
    name: str = "base"
    is_live: bool = False
    connected: bool = False

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]: ...

    @abstractmethod
    async def place_order(self, order: Order, quote: Optional[Quote] = None) -> Order: ...

    @abstractmethod
    async def refresh_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order: Order) -> Order: ...

    async def get_cash(self) -> Optional[float]:
        return None

    def on_quotes(self, quotes: Dict[str, Quote]) -> None:
        """Hook para brokers simulados que necesitan las cotizaciones del feed."""

    async def disconnect(self) -> None:
        self.connected = False
