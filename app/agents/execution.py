"""Subagente: Analista de Ejecución de Operaciones."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from ..brokers.base import Broker, BrokerError
from ..models import Order, OrderProposal, Position, Quote, Side, Trade
from .base import Agent


class ExecutionAnalyst(Agent):
    name = "execution"
    title = "Analista de Ejecución"
    mission = ("Ejecutar sólo órdenes aprobadas por el Analista Jefe con órdenes límite protegidas, "
               "controlar slippage, gestionar stops/take-profit/trailing y salidas por tiempo.")
    skills = ["execution-analyst"]

    ORDER_TIMEOUT_S = 8

    def __init__(self, settings, log_fn, broker: Broker):
        super().__init__(settings, log_fn)
        self.broker = broker

    async def _await_fill(self, order: Order) -> Order:
        if order.status in ("FILLED", "REJECTED", "CANCELLED"):
            return order
        deadline = time.time() + self.ORDER_TIMEOUT_S
        while time.time() < deadline:
            await asyncio.sleep(1)
            order = await self.broker.refresh_order(order)
            if order.status in ("FILLED", "REJECTED", "CANCELLED"):
                return order
        order = await self.broker.cancel_order(order)
        self.log(f"Orden {order.id} {order.symbol} sin completar en {self.ORDER_TIMEOUT_S}s: cancelada "
                 f"(ejecutado {order.filled_qty}/{order.quantity})", "warning")
        return order

    def _fees(self, order: Order) -> float:
        return order.fees or self.settings.costs.fee(order.avg_price * order.filled_qty)

    # ------------------------------------------------------------------ entradas
    async def open_position(self, p: OrderProposal, qty: int, quote: Quote, minute: int) -> Optional[Position]:
        s, r = p.signal, self.settings.risk
        if quote.ask > s.entry * (1 + r.max_slippage_pct):
            self.log(f"{s.symbol}: el precio se movió ({quote.ask:,.2f} vs {s.entry:,.2f}); entrada abortada", "warning")
            return None
        limit = round(quote.ask * (1 + r.max_slippage_pct), 2)
        order = Order(s.symbol, Side.BUY, qty, limit, reason=f"Entrada {p.id}")
        try:
            order = await self.broker.place_order(order, quote)
            order = await self._await_fill(order)
        except BrokerError as e:
            self.log(f"Error de broker al comprar {s.symbol}: {e}", "error")
            return None
        if order.filled_qty <= 0:
            self.log(f"{s.symbol}: orden no ejecutada ({order.status} {order.reason})", "warning")
            return None
        px = order.avg_price
        risk_dist = s.entry - s.stop
        pos = Position(symbol=s.symbol, side=Side.BUY, quantity=order.filled_qty, entry_price=px,
                       stop=round(px - risk_dist, 4), target=round(px + (s.target - s.entry), 4),
                       initial_stop=round(px - risk_dist, 4), sleeve=p.sleeve, risk_level=s.risk_level,
                       atr=s.atr, opened_minute=minute, entry_fees=self._fees(order), last_price=quote.bid,
                       max_favorable=px)
        self.log(f"COMPRA {pos.symbol} x{pos.quantity} @ {px:,.2f} | SL {pos.stop:,.2f} | TP {pos.target:,.2f} "
                 f"| {pos.sleeve}", "success")
        return pos

    # ------------------------------------------------------------------ gestión de posiciones
    def update_position(self, pos: Position, quote: Quote, tighten: bool = False) -> None:
        r = self.settings.risk
        pos.last_price = quote.bid                    # valuación a precio de liquidación
        pos.max_favorable = max(pos.max_favorable, quote.bid)
        breakeven = pos.entry_price * (1 + self.settings.costs.round_trip)
        if pos.r_multiple >= r.breakeven_at_r:
            pos.stop = max(pos.stop, breakeven)
        if pos.r_multiple >= 1.0:
            pos.stop = max(pos.stop, pos.max_favorable - r.trailing_atr_mult * pos.atr)
        if tighten:
            # protección: stop a la mitad de la distancia o break-even si ya está en ganancia
            pos.stop = max(pos.stop, quote.bid - 0.5 * (quote.bid - pos.initial_stop))
            if quote.bid > breakeven:
                pos.stop = max(pos.stop, breakeven)

    def exit_reason(self, pos: Position, quote: Quote, minute: int) -> Optional[str]:
        if quote.bid <= pos.stop:
            return "TRAILING_STOP" if pos.stop > pos.initial_stop else "STOP_LOSS"
        if quote.bid >= pos.target:
            return "TAKE_PROFIT"
        if minute - pos.opened_minute >= self.settings.risk.max_holding_minutes:
            return "TIME_STOP"
        return None

    async def close_position(self, pos: Position, quote: Quote, reason: str, minute: int,
                             urgent: bool = False) -> Optional[Trade]:
        slip = self.settings.risk.max_slippage_pct * (3 if urgent else 1)
        limit = round(quote.bid * (1 - slip), 2)
        order = Order(pos.symbol, Side.SELL, pos.quantity, limit, reason=reason)
        try:
            order = await self.broker.place_order(order, quote)
            order = await self._await_fill(order)
        except BrokerError as e:
            self.log(f"Error de broker al vender {pos.symbol}: {e}. Se reintenta.", "error")
            return None
        if order.filled_qty <= 0:
            self.log(f"{pos.symbol}: venta no ejecutada ({order.status}). Se reintenta en el próximo ciclo.", "warning")
            return None
        if order.filled_qty < pos.quantity:
            # parcial: reduce posición y prorratea comisiones de entrada
            ratio = order.filled_qty / pos.quantity
            entry_fees = pos.entry_fees * ratio
            pos.entry_fees -= entry_fees
            pos.quantity -= order.filled_qty
        else:
            entry_fees = pos.entry_fees
            pos.quantity = 0             # cierre total
        gross = (order.avg_price - pos.entry_price) * order.filled_qty
        fees = entry_fees + self._fees(order)
        trade = Trade(symbol=pos.symbol, side=pos.side, quantity=order.filled_qty, entry_price=pos.entry_price,
                      exit_price=order.avg_price, sleeve=pos.sleeve, risk_level=pos.risk_level,
                      gross_pnl=round(gross, 2), fees=round(fees, 2), net_pnl=round(gross - fees, 2), reason=reason,
                      opened_at=pos.opened_at, closed_at=time.time(), held_minutes=minute - pos.opened_minute)
        lvl = "success" if trade.net_pnl > 0 else "warning"
        self.log(f"VENTA {pos.symbol} x{order.filled_qty} @ {order.avg_price:,.2f} [{reason}] "
                 f"neto ${trade.net_pnl:,.2f}", lvl)
        return trade
