"""Adaptador Primary API (Matba Rofex) vía pyRofex.

- Entorno REMARKET: demo gratuito (https://remarkets.primary.ventures) -> ideal para validar la operatoria.
- Entorno LIVE: requiere cuenta en un ALyC que habilite Primary API; configurar PRIMARY_API_URL / PRIMARY_WS_URL.
Tickers BYMA: "MERV - XMEV - {SIMBOLO} - {PLAZO}"  (ej. "MERV - XMEV - GGAL - 24hs").
"""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional

from ..models import Order, Quote, Side
from .base import Broker, BrokerError


class PrimaryBroker(Broker):
    name = "primary"

    def __init__(self, user: str, password: str, account: str, environment: str = "REMARKET",
                 settlement: Optional[str] = None):
        try:
            import pyRofex  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise BrokerError("Instalar dependencias opcionales: pip install -r requirements-brokers.txt") from e
        self.user, self.password, self.account = user, password, account
        self.environment = environment.upper()
        self.is_live = self.environment == "LIVE"
        self.settlement = settlement or os.getenv("PRIMARY_SETTLEMENT", "24hs")

    def ticker(self, symbol: str) -> str:
        return f"MERV - XMEV - {symbol} - {self.settlement}"

    @property
    def _env(self):
        import pyRofex
        return pyRofex.Environment.LIVE if self.is_live else pyRofex.Environment.REMARKET

    async def connect(self) -> None:
        import pyRofex

        def _c():
            if self.is_live:
                url, ws = os.getenv("PRIMARY_API_URL"), os.getenv("PRIMARY_WS_URL")
                if not url or not ws:
                    raise BrokerError("Para LIVE definir PRIMARY_API_URL y PRIMARY_WS_URL (provistos por tu ALyC)")
                pyRofex._set_environment_parameter("url", url, self._env)
                pyRofex._set_environment_parameter("ws", ws, self._env)
            pyRofex.initialize(user=self.user, password=self.password, account=self.account, environment=self._env)
        await asyncio.to_thread(_c)
        self.connected = True

    def _quote(self, symbol: str) -> Optional[Quote]:
        import pyRofex
        md = pyRofex.get_market_data(
            ticker=self.ticker(symbol),
            entries=[pyRofex.MarketDataEntry.BIDS, pyRofex.MarketDataEntry.OFFERS,
                     pyRofex.MarketDataEntry.LAST, pyRofex.MarketDataEntry.TRADE_VOLUME],
            environment=self._env,
        )
        d = md.get("marketData") or {}
        bi = (d.get("BI") or [{}])[0].get("price") or 0
        of = (d.get("OF") or [{}])[0].get("price") or 0
        la = (d.get("LA") or {}).get("price") or 0
        tv = d.get("TV") or 0
        if not (bi or of or la):
            return None
        return Quote(symbol, float(bi or la), float(of or la), float(la or (bi + of) / 2), float(tv or 0))

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        res = await asyncio.gather(*[asyncio.to_thread(self._quote, s) for s in symbols], return_exceptions=True)
        return {s: q for s, q in zip(symbols, res) if isinstance(q, Quote)}

    async def place_order(self, order: Order, quote: Optional[Quote] = None) -> Order:
        import pyRofex

        def _p():
            r = pyRofex.send_order(
                ticker=self.ticker(order.symbol),
                side=pyRofex.Side.BUY if order.side == Side.BUY else pyRofex.Side.SELL,
                size=order.quantity, price=round(order.limit_price, 2),
                order_type=pyRofex.OrderType.LIMIT, time_in_force=pyRofex.TimeInForce.DAY,
                environment=self._env,
            )
            if r.get("status") != "OK":
                order.status, order.reason = "REJECTED", str(r)[:200]
            else:
                order.broker_ref, order.status = r["order"]["clientId"], "NEW"
            return order
        return await asyncio.to_thread(_p)

    async def refresh_order(self, order: Order) -> Order:
        import pyRofex

        def _r():
            if not order.broker_ref:
                return order
            o = (pyRofex.get_order_status(order.broker_ref, environment=self._env) or {}).get("order", {})
            st = o.get("status", "")
            order.filled_qty = int(o.get("cumQty") or 0)
            order.avg_price = float(o.get("avgPx") or 0)
            order.status = {"FILLED": "FILLED", "PARTIALLY_FILLED": "PARTIAL", "CANCELLED": "CANCELLED",
                            "REJECTED": "REJECTED"}.get(st, "NEW")
            return order
        return await asyncio.to_thread(_r)

    async def cancel_order(self, order: Order) -> Order:
        import pyRofex
        if order.broker_ref:
            env = self._env
            await asyncio.to_thread(lambda: pyRofex.cancel_order(order.broker_ref, environment=env))
        return await self.refresh_order(order)
