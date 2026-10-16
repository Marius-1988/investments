"""Orquestador: ciclo de decisión multi-agente, scheduler de horario y controles manuales.

Flujo por tick:
  datos -> Jefe (ánimo + circuit breakers + supervisión) -> Ejecución (gestiona salidas)
        -> Riesgo (señales) -> Carteras (tamaño) -> Jefe (veto/aprobación) -> Ejecución (entradas)
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from datetime import date
from typing import Deque, Dict, List, Optional

from .agents.broker_connection import BrokerConnectionAnalyst
from .agents.chief import ChiefMarketAnalyst
from .agents.execution import ExecutionAnalyst
from .agents.portfolio_manager import MultiPortfolioManager
from .agents.risk_analyst import ShortTermRiskAnalyst
from .brokers.base import Broker, BrokerError
from .brokers.paper import PaperBroker
from .config import Settings
from .data.base import MarketDataFeed
from .data.broker_feed import BrokerQuoteFeed
from .data.simulator import SimulatedFeed
from .journal import Journal
from .market_hours import MarketCalendar
from .market_state import MarketState
from .models import Position, SystemState, Trade, to_dict

LIVE_CONFIRMATION = "CONFIRMO OPERAR CON DINERO REAL"


class TradingSystem:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.calendar = MarketCalendar(settings.market_hours)
        self.journal = Journal()
        self.symbols = [i.symbol for i in settings.universe]
        self.activity: Deque[dict] = deque(maxlen=400)
        self.decisions: Deque[dict] = deque(maxlen=300)
        self.equity_curve: Deque[dict] = deque(maxlen=3000)
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        self.state = SystemState.STOPPED
        self.state_reason = "Esperando inicio"
        self.manual_stop_date: Optional[date] = None
        self.current_day: Optional[date] = None
        self.lock = asyncio.Lock()
        self.loop_task: Optional[asyncio.Task] = None
        self.last_gate: dict = {}
        self.last_session: dict = {}
        self.ticks = 0

        self.broker: Broker = PaperBroker(settings.costs, settings.capital_ars)
        self.feed: MarketDataFeed = self._make_feed()
        self.market = MarketState(self.symbols)
        self.feed_ready = False

        static = {i.symbol: i.static_risk for i in settings.universe}
        self.chief = ChiefMarketAnalyst(settings, self._log, self.calendar)
        self.broker_analyst = BrokerConnectionAnalyst(settings, self._log)
        self.risk = ShortTermRiskAnalyst(settings, self._log, static)
        self.portfolio = MultiPortfolioManager(settings, self._log)
        self.execution = ExecutionAnalyst(settings, self._log, self.broker)

    # ------------------------------------------------------------------ util
    def _make_feed(self) -> MarketDataFeed:
        if self.settings.data_feed == "yfinance":
            from .data.yfinance_feed import YFinanceFeed
            return YFinanceFeed()
        if self.settings.data_feed == "broker":
            return BrokerQuoteFeed(self.broker)
        return SimulatedFeed(self.settings.universe)

    def _log(self, agent: str, level: str, msg: str, data: dict) -> None:
        rec = {"ts": time.time(), "agent": agent, "level": level, "msg": msg}
        self.activity.appendleft(rec)
        self.journal.write("log", rec)

    @property
    def simulated(self) -> bool:
        return self.feed.accelerated

    @property
    def realized(self) -> float:
        return sum(t.net_pnl for t in self.trades)

    @property
    def unrealized(self) -> float:
        # neto estimado: descuenta comisiones de entrada y de salida estimadas
        return sum(p.unrealized_pnl - p.entry_fees - self.settings.costs.fee(p.last_price * p.quantity)
                   for p in self.positions.values())

    @property
    def equity(self) -> float:
        return self.settings.capital_ars + self.realized + self.unrealized

    @property
    def exposure(self) -> float:
        return sum(p.notional for p in self.positions.values())

    # ------------------------------------------------------------------ controles
    async def start(self, manual: bool = True) -> None:
        async with self.lock:
            if self.state == SystemState.HALTED and self.chief.day.halted_reason:
                self._log("chief", "warning", f"No se puede iniciar: circuit breaker activo ({self.chief.day.halted_reason})", {})
                return
            if self.state == SystemState.RUNNING:
                return
            if manual:
                self.manual_stop_date = None
            if not self.feed_ready:
                hist = await self.feed.connect(self.symbols)
                self.market.load_history(hist)
                self.feed_ready = True
            if not self.broker.connected:
                await self.broker.connect()
            self.state = SystemState.RUNNING
            self.state_reason = "Inicio manual" if manual else "Inicio automático por horario de mercado"
            self._log("chief", "info", f"Sistema INICIADO ({self.state_reason}). Modo {self.mode_label}", {})
            if not self.loop_task or self.loop_task.done():
                self.loop_task = asyncio.create_task(self._run_loop())

    async def pause(self) -> None:
        if self.state == SystemState.RUNNING:
            self.state, self.state_reason = SystemState.PAUSED, "Pausa manual: sin entradas, gestionando salidas"
            self._log("chief", "warning", self.state_reason, {})

    async def resume(self) -> None:
        if self.state == SystemState.PAUSED:
            self.state, self.state_reason = SystemState.RUNNING, "Reanudado manualmente"
            self._log("chief", "info", self.state_reason, {})

    async def stop(self, reason: str = "Detención manual", manual: bool = True) -> None:
        async with self.lock:
            await self._flatten_all(reason, urgent=False)
            self.state, self.state_reason = SystemState.STOPPED, reason
            if manual:
                self.manual_stop_date = self.calendar.now().date()
            self._log("chief", "warning", f"Sistema DETENIDO: {reason}", {})

    async def kill(self) -> None:
        async with self.lock:
            await self._flatten_all("KILL SWITCH", urgent=True)
            self.state, self.state_reason = SystemState.HALTED, "KILL SWITCH manual: todo cerrado"
            self.chief.day.halted_reason = "Kill switch manual"
            self.manual_stop_date = self.calendar.now().date()
            self._log("chief", "error", "KILL SWITCH activado: posiciones cerradas y operación bloqueada por hoy", {})

    async def reset(self) -> None:
        async with self.lock:
            if self.state in (SystemState.RUNNING, SystemState.PAUSED):
                await self._flatten_all("Reinicio del sistema a $1.000.000", urgent=True)
            self.trades.clear()
            self.positions.clear()
            self.activity.clear()
            self.decisions.clear()
            self.equity_curve.clear()
            self.manual_stop_date = None
            if not self.broker.is_live:
                from .brokers.paper import PaperBroker
                self.broker = PaperBroker(self.settings.costs, self.settings.capital_ars)
                self.execution.broker = self.broker
            self.chief.reset_day(self.settings.capital_ars)
            self.state = SystemState.STOPPED
            self.state_reason = "Reiniciado a cero ($1.000.000)"
            self._record_equity()
            self._log("chief", "info", f"Sistema reiniciado a cero con capital base ${self.settings.capital_ars:,.0f}", {})

    async def _flatten_all(self, reason: str, urgent: bool) -> None:
        for pos in list(self.positions.values()):
            q = self.market.quotes.get(pos.symbol)
            if q:
                trade = await self.execution.close_position(pos, q, reason, self.market.minute, urgent=urgent)
                if trade:
                    self._register_trade(pos, trade)

    def _register_trade(self, pos: Position, trade: Trade) -> None:
        self.trades.append(trade)
        if pos.quantity <= 0:            # cierre total (ExecutionAnalyst pone qty=0); parcial: queda abierta
            self.positions.pop(pos.symbol, None)
        self.portfolio.on_trade_closed(trade)
        self.chief.on_trade_closed(trade, self.market.minute)
        self.journal.write("trade", trade)

    @property
    def mode_label(self) -> str:
        return "LIVE (dinero real)" if self.broker.is_live else f"PAPER ({self.broker.name}/{self.feed.name})"

    # ------------------------------------------------------------------ ciclo principal
    async def _run_loop(self) -> None:
        while self.state in (SystemState.RUNNING, SystemState.PAUSED):
            t0 = time.time()
            try:
                async with self.lock:
                    if self.state in (SystemState.RUNNING, SystemState.PAUSED):
                        await self.tick()
            except Exception as e:  # el loop nunca debe morir silenciosamente
                self._log("chief", "error", f"Error en ciclo: {e!r}", {})
            await asyncio.sleep(max(0.2, self.settings.tick_seconds - (time.time() - t0)))

    async def tick(self) -> None:
        self.ticks += 1
        quotes, closed = await self.feed.step()
        self.broker.on_quotes(quotes)
        self.market.update(quotes, closed)
        minute = self.market.minute

        session = self.chief.session(self.simulated)
        self.last_session = session.to_dict()
        self.chief.assess_mood(self.market)
        gate = self.chief.risk_gate(self.equity)
        self.last_gate = gate

        # 1) supervisión del Jefe
        tighten = False
        for act in self.chief.supervise(session, gate):
            if act["action"] in ("FLATTEN_ALL", "HALT") and self.positions:
                self._log("chief", "warning", f"Orden del Jefe: cerrar todo – {act['reason']}", {})
                await self._flatten_all(act["reason"], urgent=True)
            if act["action"] == "HALT":
                self.state, self.state_reason = SystemState.HALTED, f"Circuit breaker: {act['reason']}"
                self._log("chief", "error", self.state_reason, {})
                self._record_equity()
                return
            if act["action"] == "TIGHTEN_STOPS":
                tighten = True

        # 2) gestión de posiciones abiertas (salidas primero, siempre)
        for pos in list(self.positions.values()):
            q = quotes.get(pos.symbol) or self.market.quotes.get(pos.symbol)
            if not q:
                continue
            self.execution.update_position(pos, q, tighten=tighten)
            reason = self.execution.exit_reason(pos, q, minute)
            if reason:
                trade = await self.execution.close_position(pos, q, reason, minute)
                if trade:
                    self._register_trade(pos, trade)

        # 3) nuevas entradas (sólo en vela nueva para no duplicar análisis)
        if closed and self.state == SystemState.RUNNING:
            signals = self.risk.analyze(self.market)
            for sig in signals[:5]:
                prop, why = self.portfolio.build_proposal(sig, list(self.positions.values()))
                if not prop:
                    continue
                d = self.chief.validate(prop, minute=minute, session=session, gate=gate, equity=self.equity,
                                        exposure=self.exposure, entries_enabled=self.state == SystemState.RUNNING,
                                        open_positions=list(self.positions.values()))
                rec = {**to_dict(d), "sleeve": prop.sleeve, "notes": prop.notes, "confidence": sig.confidence,
                       "risk_level": sig.risk_level.value}
                self.decisions.appendleft(rec)
                self.journal.write("decision", rec)
                if not d.approved:
                    continue
                q = self.market.quotes.get(sig.symbol)
                pos = await self.execution.open_position(prop, d.adjusted_quantity or prop.quantity, q, minute)
                if pos:
                    self.positions[pos.symbol] = pos
                    self.journal.write("position_open", pos)
        elif closed:
            self.risk.analyze(self.market)   # sigue midiendo riesgo aunque esté en pausa
        self._record_equity()

    def _record_equity(self) -> None:
        day_pnl = round(self.chief.day.realized + self.unrealized, 2)
        tot_pnl = round(self.equity - self.settings.capital_ars, 2)
        self.equity_curve.append({"ts": time.time(), "equity": round(self.equity, 2),
                                  "pnl": day_pnl, "day_pnl": day_pnl, "total_pnl": tot_pnl,
                                  "realized": round(self.realized, 2), "unrealized": round(self.unrealized, 2)})

    # ------------------------------------------------------------------ scheduler (auto on/off)
    async def scheduler_loop(self) -> None:
        while True:
            try:
                await self._schedule_check()
            except Exception as e:
                self._log("chief", "error", f"Scheduler: {e!r}", {})
            await asyncio.sleep(15)

    async def _schedule_check(self) -> None:
        st = self.calendar.status()
        today = st.now.date()
        if self.current_day != today:
            self.current_day = today
            if self.state == SystemState.HALTED:
                self.state, self.state_reason = SystemState.STOPPED, "Nuevo día: circuit breaker reseteado"
            self.chief.reset_day(self.equity)
        self.last_session = self.chief.session(self.simulated).to_dict()
        enforce = not (self.simulated and self.settings.market_hours.ignore_schedule_in_simulation)
        if (self.settings.market_hours.auto_start and st.is_open and self.state == SystemState.STOPPED
                and self.manual_stop_date != today and not self.chief.day.halted_reason):
            await self.start(manual=False)
        elif enforce and not st.is_open and self.state in (SystemState.RUNNING, SystemState.PAUSED):
            await self.stop(f"Apagado automático: {st.reason}", manual=False)

    # ------------------------------------------------------------------ broker
    async def connect_broker(self, broker_id: str, creds: dict, confirmation: str = "") -> dict:
        if self.state in (SystemState.RUNNING, SystemState.PAUSED):
            raise BrokerError("Detené el sistema antes de cambiar de broker")
        if self.positions:
            raise BrokerError("Hay posiciones abiertas: cerralas antes de cambiar de broker")
        broker: Broker
        if broker_id == "paper":
            broker = PaperBroker(self.settings.costs, self.settings.capital_ars)
        elif broker_id == "iol":
            from .brokers.iol import IOLBroker
            broker = IOLBroker(creds.get("username") or os.getenv("IOL_USERNAME", ""),
                               creds.get("password") or os.getenv("IOL_PASSWORD", ""))
        elif broker_id == "primary":
            from .brokers.primary import PrimaryBroker
            broker = PrimaryBroker(creds.get("user") or os.getenv("PRIMARY_USER", ""),
                                   creds.get("password") or os.getenv("PRIMARY_PASSWORD", ""),
                                   creds.get("account") or os.getenv("PRIMARY_ACCOUNT", ""),
                                   creds.get("environment") or os.getenv("PRIMARY_ENVIRONMENT", "REMARKET"))
        else:
            raise BrokerError(f"Broker '{broker_id}' sin adaptador implementado")

        if broker.is_live:
            if not self.settings.live_allowed_by_env:
                raise BrokerError("Operar con dinero real requiere ALLOW_LIVE_TRADING=true en .env")
            if confirmation.strip().upper() != LIVE_CONFIRMATION:
                raise BrokerError(f"Para operar en vivo escribí exactamente: '{LIVE_CONFIRMATION}'")

        await broker.connect()
        cash = await broker.get_cash()
        self.broker = broker
        self.execution.broker = broker
        # con broker real los precios DEBEN venir del broker (nunca operar real con precios simulados)
        self.feed = BrokerQuoteFeed(broker) if broker_id != "paper" else self._make_feed()
        self.market = MarketState(self.symbols)
        self.feed_ready = False
        self._log("broker_analyst", "success" if not broker.is_live else "warning",
                  f"Conectado a {broker.name} ({'LIVE' if broker.is_live else 'demo/paper'}). Saldo: {cash}", {})
        return {"broker": broker.name, "live": broker.is_live, "cash": cash, "feed": self.feed.name}

    # ------------------------------------------------------------------ snapshot UI
    def snapshot(self, full_curve: bool = False) -> dict:
        trades = self.trades
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        gw, gl = sum(t.net_pnl for t in wins), -sum(t.net_pnl for t in losses)
        r = self.settings.risk
        d = self.chief.day
        day_pnl = d.realized + self.unrealized
        day_pnl_pct = (day_pnl / d.start_equity) if d.start_equity else 0.0
        tot_pnl = self.equity - self.settings.capital_ars
        tot_pnl_pct = (self.equity / self.settings.capital_ars - 1) if self.settings.capital_ars else 0.0
        curve = list(self.equity_curve)
        return {
            "ts": time.time(),
            "state": self.state.value, "state_reason": self.state_reason,
            "mode": self.mode_label, "live": self.broker.is_live, "broker": self.broker.name, "feed": self.feed.name,
            "session": self.last_session or self.chief.session(self.simulated).to_dict(),
            "capital": self.settings.capital_ars,
            "kpis": {
                "equity": round(self.equity, 2),
                "day_pnl": round(day_pnl, 2),
                "day_pnl_pct": day_pnl_pct,
                "total_pnl": round(tot_pnl, 2),
                "total_pnl_pct": tot_pnl_pct,
                "pnl": round(day_pnl, 2),
                "pnl_pct": day_pnl_pct,
                "realized": round(self.realized, 2), "unrealized": round(self.unrealized, 2),
                "trades": len(trades), "win_rate": len(wins) / len(trades) if trades else None,
                "profit_factor": (gw / gl) if gl > 0 else (999.0 if wins else None),
                "avg_win": gw / len(wins) if wins else 0, "avg_loss": -gl / len(losses) if losses else 0,
                "exposure": round(self.exposure, 2), "exposure_pct": self.exposure / self.equity if self.equity else 0,
                "fees": round(sum(t.fees for t in trades), 2),
            },
            "risk": {
                "gate": {k: v for k, v in self.last_gate.items()},
                "limits": {"daily_max_loss_pct": r.daily_max_loss_pct, "max_drawdown_pct": r.max_drawdown_pct,
                           "daily_profit_lock_pct": r.daily_profit_lock_pct, "risk_per_trade_pct": r.risk_per_trade_pct,
                           "min_holding_minutes": r.min_holding_minutes, "max_holding_minutes": r.max_holding_minutes,
                           "max_total_exposure_pct": r.max_total_exposure_pct,
                           "round_trip_cost_pct": self.settings.costs.round_trip,
                           "max_consecutive_losses": r.max_consecutive_losses},
                "consecutive_losses": d.consecutive_losses,
                "cooldown_active": self.market.minute < d.cooldown_until_minute,
                "halted_reason": d.halted_reason,
                "trades_last_hour": len([m for m in d.trade_minutes if self.market.minute - m < 60]),
                "max_trades_per_hour": r.max_trades_per_hour,
            },
            "mood": self.chief.mood,
            "sleeves": self.portfolio.report(list(self.positions.values())),
            "positions": [{**to_dict(p), "held_min": self.market.minute - p.opened_minute}
                          for p in self.positions.values()],
            "assessments": self.risk.last_assessments,
            "decisions": list(self.decisions)[:60],
            "activity": list(self.activity)[:120],
            "trades": [to_dict(t) for t in reversed(self.trades[-80:])],
            "equity_curve": curve if full_curve else curve[-600:],
            "agents": [a.describe() for a in (self.chief, self.broker_analyst, self.risk, self.portfolio, self.execution)],
            "minute": self.market.minute, "ticks": self.ticks,
        }
