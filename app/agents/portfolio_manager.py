"""Subagente: Analista de Múltiples Carteras (perfil conservador 80/20)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import OrderProposal, Position, RiskLevel, Signal, Trade
from .base import Agent


@dataclass
class Sleeve:
    name: str
    weight: float
    allowed_risk: List[str]
    max_open_positions: int
    base_capital: float
    realized_pnl: float = 0.0
    trades: int = 0
    wins: int = 0

    @property
    def capital(self) -> float:
        return self.base_capital + self.realized_pnl


class MultiPortfolioManager(Agent):
    name = "portfolio_manager"
    title = "Analista de Múltiples Carteras"
    mission = ("Distribuir el capital en carteras por nivel de riesgo (80% bajo/medio, 20% alto), "
               "dimensionar cada operación por riesgo fijo y mantener los límites de cada cartera.")
    skills = ["multi-portfolio-manager"]

    def __init__(self, settings, log_fn):
        super().__init__(settings, log_fn)
        cap = settings.capital_ars
        p = settings.portfolios
        self.sleeves: Dict[str, Sleeve] = {
            "conservative": Sleeve("conservative", p.conservative.weight, list(p.conservative.allowed_risk),
                                   p.conservative.max_open_positions, cap * p.conservative.weight),
            "aggressive": Sleeve("aggressive", p.aggressive.weight, list(p.aggressive.allowed_risk),
                                 p.aggressive.max_open_positions, cap * p.aggressive.weight),
        }

    def sleeve_for(self, level: RiskLevel) -> Optional[Sleeve]:
        for s in self.sleeves.values():
            if level.value in s.allowed_risk:
                return s
        return None

    def build_proposal(self, signal: Signal, positions: List[Position]) -> Tuple[Optional[OrderProposal], str]:
        sleeve = self.sleeve_for(signal.risk_level)
        if sleeve is None:
            return None, f"Sin cartera para riesgo {signal.risk_level.value}"
        if any(p.symbol == signal.symbol for p in positions):
            return None, f"{signal.symbol}: ya hay posición abierta"
        in_sleeve = [p for p in positions if p.sleeve == sleeve.name]
        if len(in_sleeve) >= sleeve.max_open_positions:
            return None, f"Cartera {sleeve.name} completa ({len(in_sleeve)}/{sleeve.max_open_positions})"

        r = self.settings.risk
        per_side = self.settings.costs.per_side
        used = sum(p.notional for p in in_sleeve)
        available = max(0.0, sleeve.capital - used)
        per_unit_risk = signal.entry - signal.stop + signal.entry * self.settings.costs.round_trip
        if per_unit_risk <= 0:
            return None, "Riesgo por unidad inválido"
        qty_risk = math.floor(sleeve.capital * r.risk_per_trade_pct / per_unit_risk)
        qty_cap = math.floor(sleeve.capital * r.max_position_pct_of_sleeve / signal.entry)
        qty_cash = math.floor(available / (signal.entry * (1 + per_side)))
        qty = min(qty_risk, qty_cap, qty_cash)
        if qty < 1:
            return None, f"{signal.symbol}: tamaño < 1 (riesgo {qty_risk}, tope {qty_cap}, caja {qty_cash})"
        notional = qty * signal.entry
        prop = OrderProposal(signal=signal, sleeve=sleeve.name, quantity=qty, notional=notional,
                             est_round_trip_cost=notional * self.settings.costs.round_trip)
        binding = min((qty_risk, "riesgo fijo"), (qty_cap, "tope por posición"), (qty_cash, "caja disponible"))[1]
        prop.notes.append(f"Tamaño limitado por {binding}; riesgo máx ≈ ${qty * per_unit_risk:,.0f}")
        return prop, "ok"

    def on_trade_closed(self, trade: Trade) -> None:
        s = self.sleeves.get(trade.sleeve)
        if s:
            s.realized_pnl += trade.net_pnl
            s.trades += 1
            s.wins += 1 if trade.net_pnl > 0 else 0

    def report(self, positions: List[Position]) -> List[dict]:
        total_invested = sum(p.notional for p in positions) or 0.0
        out = []
        for s in self.sleeves.values():
            ps = [p for p in positions if p.sleeve == s.name]
            invested = sum(p.notional for p in ps)
            out.append({
                "name": s.name, "target_weight": s.weight, "allowed_risk": s.allowed_risk,
                "capital": round(s.capital, 2), "invested": round(invested, 2),
                "utilization": round(invested / s.capital, 4) if s.capital else 0,
                "share_of_invested": round(invested / total_invested, 4) if total_invested else 0,
                "open_positions": len(ps), "max_open_positions": s.max_open_positions,
                "realized_pnl": round(s.realized_pnl, 2),
                "unrealized_pnl": round(sum(p.unrealized_pnl for p in ps), 2),
                "trades": s.trades, "win_rate": round(s.wins / s.trades, 3) if s.trades else None,
            })
        return out
