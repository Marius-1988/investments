"""Adaptador InvertirOnline (IOL) – API REST pública v2.

Documentación: https://api.invertironline.com/  (habilitar "API" desde la cuenta IOL).
IMPORTANTE: validar endpoints/campos contra la documentación vigente antes de operar en vivo.
Credenciales: IOL_USERNAME / IOL_PASSWORD en .env (o ingresadas en la UI; se guardan solo en memoria).
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

from ..models import Order, Quote, Side
from .base import Broker, BrokerError

BASE = "https://api.invertironline.com"


class IOLBroker(Broker):
    name = "iol"
    is_live = True

    def __init__(self, username: str, password: str, market: str = "bCBA", plazo: Optional[str] = None):
        self.username, self.password, self.market = username, password, market
        self.plazo = plazo or os.getenv("IOL_PLAZO", "t1")
        self.token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at = 0.0
        self.session = requests.Session()

    # ------------------------------------------------------------------ auth
    def _auth(self, refresh: bool = False) -> None:
        data = ({"refresh_token": self.refresh_token, "grant_type": "refresh_token"} if refresh and self.refresh_token
                else {"username": self.username, "password": self.password, "grant_type": "password"})
        r = self.session.post(f"{BASE}/token", data=data, timeout=15)
        if r.status_code != 200:
            raise BrokerError(f"IOL login falló ({r.status_code}): {r.text[:200]}")
        j = r.json()
        self.token, self.refresh_token = j["access_token"], j.get("refresh_token")
        self.expires_at = time.time() + int(j.get("expires_in", 900)) - 60

    def _headers(self) -> dict:
        if not self.token or time.time() > self.expires_at:
            self._auth(refresh=bool(self.refresh_token))
        return {"Authorization": f"Bearer {self.token}"}

    def _get(self, path: str) -> dict:
        r = self.session.get(f"{BASE}{path}", headers=self._headers(), timeout=10)
        if r.status_code >= 400:
            raise BrokerError(f"IOL GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # ------------------------------------------------------------------ api
    async def connect(self) -> None:
        await asyncio.to_thread(self._auth)
        self.connected = True

    def _quote(self, symbol: str) -> Optional[Quote]:
        j = self._get(f"/api/v2/{self.market}/Titulos/{symbol}/Cotizacion")
        last = float(j.get("ultimoPrecio") or 0)
        puntas = j.get("puntas") or []
        if isinstance(puntas, dict):
            puntas = [puntas]
        bid = float(puntas[0].get("precioCompra") or 0) if puntas else 0.0
        ask = float(puntas[0].get("precioVenta") or 0) if puntas else 0.0
        return Quote(symbol, bid or last, ask or last, last, float(j.get("volumenNominal") or 0))

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        results = await asyncio.gather(*[asyncio.to_thread(self._quote, s) for s in symbols], return_exceptions=True)
        return {s: q for s, q in zip(symbols, results) if isinstance(q, Quote)}

    def _place(self, order: Order) -> Order:
        path = "/api/v2/operar/Comprar" if order.side == Side.BUY else "/api/v2/operar/Vender"
        payload = {
            "mercado": self.market,
            "simbolo": order.symbol,
            "cantidad": order.quantity,
            "precio": round(order.limit_price, 2),
            "plazo": self.plazo,
            "validez": datetime.now().strftime("%Y-%m-%dT17:00:00"),
        }
        r = self.session.post(f"{BASE}{path}", json=payload, headers=self._headers(), timeout=15)
        j = r.json() if r.content else {}
        if r.status_code >= 400 or not j.get("ok", True):
            order.status, order.reason = "REJECTED", str(j)[:200]
            return order
        order.broker_ref = str(j.get("numeroOperacion"))
        order.status = "NEW"
        return order

    async def place_order(self, order: Order, quote: Optional[Quote] = None) -> Order:
        return await asyncio.to_thread(self._place, order)

    def _refresh(self, order: Order) -> Order:
        if not order.broker_ref:
            return order
        j = self._get(f"/api/v2/operaciones/{order.broker_ref}")
        estado = str(j.get("estado", "")).lower()
        fills = j.get("operaciones") or []
        qty = sum(int(f.get("cantidad", 0)) for f in fills)
        if qty:
            order.filled_qty = qty
            order.avg_price = sum(float(f.get("precio", 0)) * int(f.get("cantidad", 0)) for f in fills) / qty
        if "terminada" in estado:
            order.status = "FILLED"
        elif "cancelada" in estado or "rechazada" in estado:
            order.status = "CANCELLED" if qty == 0 else "PARTIAL"
        elif qty:
            order.status = "PARTIAL"
        order.fees = float(j.get("aranceles", 0) or 0) if isinstance(j.get("aranceles"), (int, float)) else order.fees
        return order

    async def refresh_order(self, order: Order) -> Order:
        return await asyncio.to_thread(self._refresh, order)

    async def cancel_order(self, order: Order) -> Order:
        def _c():
            if order.broker_ref:
                self.session.delete(f"{BASE}/api/v2/operaciones/{order.broker_ref}", headers=self._headers(), timeout=10)
            return self._refresh(order)
        return await asyncio.to_thread(_c)

    async def get_cash(self) -> Optional[float]:
        def _cash():
            j = self._get("/api/v2/estadocuenta")
            for c in j.get("cuentas", []):
                if "peso" in str(c.get("moneda", "")).lower():
                    return float(c.get("disponible", 0))
            return None
        return await asyncio.to_thread(_cash)
