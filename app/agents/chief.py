"""Agente principal: Analista Jefe de Mercado (supervisor con poder de veto).

Prioridad absoluta: preservar capital. Ninguna orden llega al mercado sin su aprobación.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from ..indicators import returns, stdev, zscore
from ..market_hours import MarketCalendar, SessionStatus
from ..market_state import MarketState
from ..models import Decision, OrderProposal, Regime, Side, Trade
from .base import Agent

CONFIRM_SIZE = {Regime.CALM: 1.0, Regime.TRENDING_UP: 1.0, Regime.VOLATILE: 0.5}


@dataclass
class DayStats:
    start_equity: float
    peak_equity: float
    realized: float = 0.0
    trades: int = 0
    wins: int = 0
    gross_win: float = 0.0
    gross_loss: float = 0.0
    consecutive_losses: int = 0
    cooldown_until_minute: int = -1
    trade_minutes: Deque[int] = field(default_factory=lambda: deque(maxlen=500))
    halted_reason: Optional[str] = None
    profit_locked: bool = False
    symbol_cooldown: Dict[str, int] = field(default_factory=dict)   # símbolo -> minuto hasta el que no se re-entra


class ChiefMarketAnalyst(Agent):
    name = "chief"
    title = "Analista Jefe de Mercado"
    mission = ("Validar y controlar cada decisión de los subagentes priorizando perder lo menos posible: "
               "márgenes de ganancia claros, cortes máximos/mínimos, lectura del ánimo del mercado y "
               "bloqueo de ventanas horarias de alto riesgo.")
    skills = ["chief-market-analyst"]

    def __init__(self, settings, log_fn, calendar: MarketCalendar):
        super().__init__(settings, log_fn)
        self.calendar = calendar
        self.day = DayStats(settings.capital_ars, settings.capital_ars)
        self.regime_hist: Deque[Regime] = deque(maxlen=10)
        self.mood: dict = {"regime": Regime.WARMUP.value, "score": 0, "entries_allowed": False,
                           "size_multiplier": 0, "anomalies": [], "reason": "Calentando indicadores"}

    # ------------------------------------------------------------------ día
    def reset_day(self, equity: float) -> None:
        self.day = DayStats(equity, equity)
        self.regime_hist.clear()
        self.log(f"Nuevo día operativo. Equity inicial ${equity:,.0f}", "info")

    # ------------------------------------------------------------------ sesión
    def session(self, simulated: bool) -> SessionStatus:
        st = self.calendar.status()
        if simulated and self.settings.market_hours.ignore_schedule_in_simulation:
            return SessionStatus(True, True, "SIMULATION", True, False, st.now, None, None,
                                 "Simulación: horario ignorado (configurable)")
        return st

    # ------------------------------------------------------------------ ánimo de mercado
    def assess_mood(self, market: MarketState) -> dict:
        m = self.settings.mood
        idx = list(market.index)
        if len(idx) < 31:
            self.mood = {"regime": Regime.WARMUP.value, "score": 0, "entries_allowed": False, "size_multiplier": 0,
                         "anomalies": [], "reason": f"Calentando ({len(idx)}/31 velas)", "breadth": None,
                         "vol_ratio": None, "index_z": None, "trend_15m_pct": None, "spread_ratio": None}
            return self.mood
        rets = returns(idx[-61:])
        z = zscore(rets[-1], rets[:-1])
        vol_l = stdev(rets) or 1e-9
        vol_ratio = stdev(rets[-10:]) / vol_l
        trend = idx[-1] / idx[-16] - 1

        ups, total = 0, 0
        for s in market.symbols:
            c = market.closes(s)
            if len(c) > 5:
                total += 1
                ups += 1 if c[-1] > c[-6] else 0
        breadth = ups / total if total else 0.5

        ratios = []
        for s in market.symbols:
            sp = list(market.spreads[s])
            if len(sp) > 20:
                base = sum(sp[:-5]) / len(sp[:-5])
                if base > 0:
                    ratios.append((sum(sp[-5:]) / 5) / base)
        spread_ratio = sum(ratios) / len(ratios) if ratios else 1.0

        anomalies = []
        if abs(z) > m.chaotic_index_z:
            anomalies.append(f"Movimiento del índice de {z:+.1f}σ en 1 minuto")
        if vol_ratio > m.chaotic_vol_ratio:
            anomalies.append(f"Volatilidad x{vol_ratio:.1f} sobre su media")
        if spread_ratio > m.spread_widening_ratio:
            anomalies.append(f"Spreads ensanchados x{spread_ratio:.1f} (liquidez en retirada)")

        if anomalies and (abs(z) > m.chaotic_index_z or vol_ratio > m.chaotic_vol_ratio
                          or spread_ratio > m.spread_widening_ratio * 1.5):
            regime = Regime.CHAOTIC
        elif vol_ratio > m.volatile_vol_ratio or spread_ratio > m.spread_widening_ratio:
            regime = Regime.VOLATILE
        elif trend > 0.003 and breadth >= 0.55:
            regime = Regime.TRENDING_UP
        elif trend < -0.003 and breadth <= 0.45:
            regime = Regime.TRENDING_DOWN
        else:
            regime = Regime.CALM

        self.regime_hist.append(regime)
        flips = sum(1 for a, b in zip(list(self.regime_hist)[:-1], list(self.regime_hist)[1:]) if a != b)
        if flips >= m.regime_flip_limit and regime != Regime.CHAOTIC:
            anomalies.append(f"{flips} cambios de régimen en {len(self.regime_hist)} ticks: mercado difícil de diagnosticar")
            regime = Regime.UNCERTAIN

        score = max(-100.0, min(100.0, trend * 10000 * 0.5 + (breadth - 0.5) * 100 - max(0.0, vol_ratio - 1) * 30))
        size_mult = CONFIRM_SIZE.get(regime, 0.0)
        entries = size_mult > 0 and breadth >= m.min_breadth_for_longs
        reason = {
            Regime.CALM: "Mercado tranquilo: operar con tamaño normal",
            Regime.TRENDING_UP: "Tendencia alcista amplia: favorable para largos",
            Regime.TRENDING_DOWN: "Tendencia bajista amplia: sin largos (long-only)",
            Regime.VOLATILE: "Volatilidad elevada: tamaño reducido al 50%",
            Regime.CHAOTIC: "Comportamiento anómalo: se frena la operación",
            Regime.UNCERTAIN: "Cambios difíciles de diagnosticar: se frenan entradas",
        }[regime]
        if size_mult > 0 and not entries:
            reason += f" | amplitud baja ({breadth:.0%})"

        prev = self.mood.get("regime")
        self.mood = {"regime": regime.value, "score": round(score, 1), "entries_allowed": entries,
                     "size_multiplier": size_mult if entries else 0, "anomalies": anomalies, "reason": reason,
                     "breadth": round(breadth, 3), "vol_ratio": round(vol_ratio, 2), "index_z": round(z, 2),
                     "trend_15m_pct": round(trend * 100, 3), "spread_ratio": round(spread_ratio, 2)}
        if prev != regime.value:
            lvl = "warning" if regime in (Regime.CHAOTIC, Regime.UNCERTAIN, Regime.TRENDING_DOWN) else "info"
            self.log(f"Régimen de mercado: {prev} → {regime.value}. {reason}", lvl)
        return self.mood

    # ------------------------------------------------------------------ circuit breakers
    def risk_gate(self, equity: float) -> dict:
        r = self.settings.risk
        d = self.day
        d.peak_equity = max(d.peak_equity, equity)
        day_pnl = equity - d.start_equity
        day_pnl_pct = day_pnl / d.start_equity if d.start_equity else 0
        dd_pct = (d.peak_equity - equity) / d.peak_equity if d.peak_equity else 0
        halt, flatten, reasons = False, False, []
        if day_pnl_pct <= -r.daily_max_loss_pct:
            halt = flatten = True
            reasons.append(f"Pérdida diaria {day_pnl_pct:.2%} alcanzó el límite (-{r.daily_max_loss_pct:.2%})")
        if dd_pct >= r.max_drawdown_pct:
            halt = flatten = True
            reasons.append(f"Drawdown intradiario {dd_pct:.2%} ≥ {r.max_drawdown_pct:.2%}")
        if day_pnl_pct >= r.daily_profit_lock_pct and not d.profit_locked:
            d.profit_locked = True
            self.log(f"Objetivo diario alcanzado (+{day_pnl_pct:.2%}). Se bloquean entradas y se protege la ganancia.", "success")
        return {"halt": halt, "flatten": flatten, "reasons": reasons, "day_pnl": day_pnl, "day_pnl_pct": day_pnl_pct,
                "drawdown_pct": dd_pct, "profit_locked": d.profit_locked,
                "daily_loss_used": min(1.0, max(0.0, -day_pnl_pct / r.daily_max_loss_pct)),
                "drawdown_used": min(1.0, dd_pct / r.max_drawdown_pct)}

    # ------------------------------------------------------------------ validación de propuestas
    def validate(self, p: OrderProposal, *, minute: int, session: SessionStatus, gate: dict,
                 equity: float, exposure: float, entries_enabled: bool) -> Decision:
        r, s = self.settings.risk, p.signal
        fails: List[str] = []
        if not entries_enabled:
            fails.append("Sistema sin entradas habilitadas (pausa/stop)")
        if not session.entries_allowed:
            fails.append(f"Horario: {session.reason}")
        if gate["halt"] or self.day.halted_reason:
            fails.append("Circuit breaker activo")
        if gate["profit_locked"]:
            fails.append("Ganancia diaria bloqueada (profit lock)")
        if minute < self.day.cooldown_until_minute:
            fails.append(f"Enfriamiento tras {r.max_consecutive_losses} pérdidas seguidas")
        if minute < self.day.symbol_cooldown.get(s.symbol, -1):
            fails.append(f"{s.symbol} en enfriamiento tras pérdida (evita 'revancha')")
        recent = [t for t in self.day.trade_minutes if minute - t < 60]
        if len(recent) >= r.max_trades_per_hour:
            fails.append(f"Límite de {r.max_trades_per_hour} operaciones/hora (evita sobre-operar)")
        if not self.mood.get("entries_allowed"):
            fails.append(f"Ánimo de mercado: {self.mood.get('reason')}")
        if s.side == Side.SELL and not self.settings.allow_short:
            fails.append("Ventas en corto deshabilitadas")
        if s.confidence < r.min_confidence:
            fails.append(f"Confianza {s.confidence:.2f} < {r.min_confidence:.2f}")
        if s.reward_risk < r.min_reward_risk:
            fails.append(f"Beneficio/riesgo {s.reward_risk:.2f} < {r.min_reward_risk}")
        cost = self.settings.costs.round_trip
        if s.target_pct < r.min_reward_cost_ratio * cost:
            fails.append(f"Objetivo {s.target_pct:.2%} no cubre {r.min_reward_cost_ratio}x costos ({cost:.2%})")
        if s.spread_pct > r.max_spread_pct:
            fails.append(f"Spread {s.spread_pct:.2%} > {r.max_spread_pct:.2%}")
        stretch = s.features.get("stretch_atr", 0)
        if stretch > 2.5:
            fails.append(f"Precio sobreextendido ({stretch:.1f} ATR sobre VWAP): no se persigue la puja")
        if abs(s.features.get("last_bar_ret", 0)) > 2.5 * s.features.get("atr_pct", 1):
            fails.append("Vela de 1m anómala: posible spike, se espera confirmación")
        if exposure + p.notional > r.max_total_exposure_pct * equity:
            fails.append(f"Exposición total superaría {r.max_total_exposure_pct:.0%} del capital")

        if fails:
            return Decision(p.id, s.symbol, False, self.name, fails)

        qty = p.quantity
        mult = self.mood.get("size_multiplier", 1.0)
        if mult < 1.0:
            qty = math.floor(qty * mult)
            if qty < 1:
                return Decision(p.id, s.symbol, False, self.name, ["Tamaño reducido por volatilidad < 1 unidad"])
        ok = [f"✔ {s.symbol} x{qty} @ {s.entry:,.2f} | SL {s.stop:,.2f} ({(s.stop / s.entry - 1):.2%}) | "
              f"TP {s.target:,.2f} (+{s.target_pct:.2%}) | B/R {s.reward_risk:.1f} | conf {s.confidence:.2f} | "
              f"cartera {p.sleeve} | régimen {self.mood.get('regime')}"]
        if qty != p.quantity:
            ok.append(f"Tamaño ajustado {p.quantity}→{qty} (x{mult}) por régimen")
        return Decision(p.id, s.symbol, True, self.name, ok, adjusted_quantity=qty)

    # ------------------------------------------------------------------ supervisión continua
    def supervise(self, session: SessionStatus, gate: dict) -> List[dict]:
        actions = []
        if gate["halt"] and not self.day.halted_reason:
            self.day.halted_reason = "; ".join(gate["reasons"])
            actions.append({"action": "HALT", "reason": self.day.halted_reason})
        if session.must_flatten:
            actions.append({"action": "FLATTEN_ALL", "reason": session.reason})
        regime = self.mood.get("regime")
        if regime == Regime.CHAOTIC.value:
            actions.append({"action": "FLATTEN_ALL", "reason": "Régimen CAÓTICO: " + "; ".join(self.mood.get("anomalies", []))})
        elif regime in (Regime.UNCERTAIN.value, Regime.TRENDING_DOWN.value) or gate["profit_locked"]:
            actions.append({"action": "TIGHTEN_STOPS", "reason": f"Proteger posiciones ({regime})"})
        return actions

    def on_trade_closed(self, trade: Trade, minute: int) -> None:
        d, r = self.day, self.settings.risk
        d.trades += 1
        d.realized += trade.net_pnl
        d.trade_minutes.append(minute)
        if trade.net_pnl > 0:
            d.wins += 1
            d.gross_win += trade.net_pnl
            d.consecutive_losses = 0
        else:
            d.gross_loss += -trade.net_pnl
            d.consecutive_losses += 1
            d.symbol_cooldown[trade.symbol] = minute + r.symbol_cooldown_minutes
            if d.consecutive_losses >= r.max_consecutive_losses:
                d.cooldown_until_minute = minute + r.cooldown_minutes_after_losses
                self.log(f"{d.consecutive_losses} pérdidas consecutivas: enfriamiento de "
                         f"{r.cooldown_minutes_after_losses} min", "warning")
                d.consecutive_losses = 0
