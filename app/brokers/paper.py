"""Broker simulado (paper trading): ejecuta contra las puntas del feed con costos reales."""
from __future__ import annotations

from typing import Dict, List, Optional

from ..config import CostsCfg
from ..models import Order, Quote, Side
from .base import Broker, BrokerError


class PaperBroker(Broker):
    name = "paper"
    is_live = False

    def __init__(self, costs: CostsCfg, cash: float):
        self.costs = costs
        self.cash = cash
        self.quotes: Dict[str, Quote] = {}

    async def connect(self) -> None:
        self.connected = True

    def on_quotes(self, quotes: Dict[str, Quote]) -> None:
        self.quotes.update(quotes)

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        return {s: self.quotes[s] for s in symbols if s in self.quotes}

    async def place_order(self, order: Order, quote: Optional[Quote] = None) -> Order:
        q = quote or self.quotes.get(order.symbol)
        if q is None:
            raise BrokerError(f"Sin cotización para {order.symbol}")
        # Semántica IOC (immediate-or-cancel) con precio límite de protección
        if order.side == Side.BUY and order.limit_price >= q.ask:
            px = q.ask
        elif order.side == Side.SELL and order.limit_price <= q.bid:
            px = q.bid
        else:
            order.status = "CANCELLED"
            order.reason = "Límite no marketable (IOC)"
            return order
        notional = px * order.quantity
        fees = self.costs.fee(notional)
        if order.side == Side.BUY and notional + fees > self.cash:
            order.status = "REJECTED"
            order.reason = "Saldo insuficiente"
            return order
        self.cash += (-notional if order.side == Side.BUY else notional) - fees
        order.status, order.filled_qty, order.avg_price, order.fees = "FILLED", order.quantity, px, fees
        order.broker_ref = f"PAPER-{order.id}"
        return order

    async def refresh_order(self, order: Order) -> Order:
        return order

    async def cancel_order(self, order: Order) -> Order:
        if order.status not in ("FILLED", "REJECTED"):
            order.status = "CANCELLED"
        return order

    async def get_cash(self) -> Optional[float]:
        return self.cash
