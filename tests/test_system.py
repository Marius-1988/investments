import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import load_settings
from app.agents.chief import ChiefMarketAnalyst
from app.agents.portfolio_manager import MultiPortfolioManager
from app.market_hours import MarketCalendar
from app.models import OrderProposal, RiskLevel, Side, Signal, Position, Quote
from app.orchestrator import TradingSystem

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
S = load_settings()
noop = lambda *a, **k: None  # noqa: E731


def sig(symbol="GGAL", level=RiskLevel.MEDIUM, entry=1000.0, atr=5.0, conf=0.8):
    stop = entry - S.risk.stop_atr_mult * atr
    target = entry + S.risk.take_profit_rr * (entry - stop)
    return Signal(symbol, Side.BUY, entry, stop, target, 3, conf, level, 30, atr, 0.002, [],
                  {"stretch_atr": 0.5, "last_bar_ret": 0.001, "atr_pct": atr / entry})


# ---------------------------------------------------------------- horario
def test_market_phases():
    cal = MarketCalendar(S.market_hours)
    wed = lambda h, m: datetime(2026, 10, 14, h, m, tzinfo=TZ)  # noqa: E731
    assert cal.status(wed(9, 0)).phase == "PRE_MARKET"
    assert cal.status(wed(10, 40)).phase == "OPENING_RISK"
    assert cal.status(wed(13, 0)).entries_allowed
    assert cal.status(wed(16, 45)).phase == "CLOSING_RISK"
    assert cal.status(wed(16, 55)).must_flatten
    assert cal.status(wed(18, 0)).phase == "CLOSED"
    assert cal.status(datetime(2026, 10, 17, 12, 0, tzinfo=TZ)).phase == "WEEKEND"


def test_holiday_blocks_trading():
    cal = MarketCalendar(S.market_hours)
    assert cal.status(datetime(2026, 5, 25, 12, 0, tzinfo=TZ)).phase == "HOLIDAY"   # Revolución de Mayo


# ---------------------------------------------------------------- carteras
def test_sleeve_split_and_sizing():
    pm = MultiPortfolioManager(S, noop)
    assert pm.sleeves["conservative"].capital == pytest.approx(S.capital_ars * 0.8)
    assert pm.sleeves["aggressive"].capital == pytest.approx(S.capital_ars * 0.2)
    prop, _ = pm.build_proposal(sig(level=RiskLevel.HIGH), [])
    assert prop.sleeve == "aggressive"
    max_risk = pm.sleeves["aggressive"].capital * S.risk.risk_per_trade_pct
    assert prop.quantity * (prop.signal.entry - prop.signal.stop) <= max_risk
    assert prop.notional <= pm.sleeves["aggressive"].capital * S.risk.max_position_pct_of_sleeve


# ---------------------------------------------------------------- jefe
def _chief_ready():
    c = ChiefMarketAnalyst(S, noop, MarketCalendar(S.market_hours))
    c.mood = {"regime": "CALM", "entries_allowed": True, "size_multiplier": 1.0, "reason": "ok"}
    return c


def _validate(c, p, **over):
    session = c.session(simulated=True)
    gate = c.risk_gate(S.capital_ars)
    kw = dict(minute=100, session=session, gate=gate, equity=S.capital_ars, exposure=0, entries_enabled=True)
    kw.update(over)
    return c.validate(p, **kw)


def test_chief_approves_good_setup():
    c = _chief_ready()
    p = OrderProposal(sig(atr=5.0), "conservative", 10, 10000, 50)
    assert _validate(c, p).approved


def test_chief_rejects_when_costs_eat_target():
    c = _chief_ready()
    p = OrderProposal(sig(atr=0.5), "conservative", 10, 10000, 50)   # objetivo diminuto
    d = _validate(c, p)
    assert not d.approved and any("costos" in r for r in d.reasons)


def test_chief_rejects_chaotic_market():
    c = _chief_ready()
    c.mood = {"regime": "CHAOTIC", "entries_allowed": False, "size_multiplier": 0, "reason": "anomalía"}
    assert not _validate(c, OrderProposal(sig(), "conservative", 10, 10000, 50)).approved


def test_circuit_breaker_daily_loss():
    c = _chief_ready()
    gate = c.risk_gate(S.capital_ars * (1 - S.risk.daily_max_loss_pct - 0.001))
    assert gate["halt"] and gate["flatten"]


def test_chief_rejects_sector_correlation():
    c = _chief_ready()
    pos_ggal = Position(symbol="GGAL", side=Side.BUY, quantity=10, entry_price=1000.0,
                        stop=987.5, target=1025.0, initial_stop=987.5, sleeve="conservative",
                        risk_level=RiskLevel.MEDIUM, atr=5.0, opened_minute=10, entry_fees=10.0,
                        last_price=1000.0, max_favorable=1000.0)
    p_bma = OrderProposal(sig(symbol="BMA", atr=5.0), "conservative", 10, 10000, 50)
    d = _validate(c, p_bma, open_positions=[pos_ggal])
    assert not d.approved
    assert any("filtro anti-correlación" in r for r in d.reasons)


def test_execution_trailing_and_breakeven():
    from app.brokers.paper import PaperBroker
    from app.agents.execution import ExecutionAnalyst
    broker = PaperBroker(S.costs, S.capital_ars)
    exec_analyst = ExecutionAnalyst(S, noop, broker)

    pos = Position(symbol="GGAL", side=Side.BUY, quantity=10, entry_price=1000.0,
                   stop=975.0, target=1050.0, initial_stop=975.0, sleeve="conservative",
                   risk_level=RiskLevel.MEDIUM, atr=10.0, opened_minute=10, entry_fees=10.0,
                   last_price=1000.0, max_favorable=1000.0)

    # precio sube a 1025 (+1.0R): stop se mueve a breakeven (+15% sobre costos round-trip)
    # pero trailing stop NO debe activarse aún porque trailing_activation_r = 1.5
    q1 = Quote(symbol="GGAL", bid=1025.0, ask=1026.0, last=1025.0, volume=100, ts=1000.0)
    exec_analyst.update_position(pos, q1)
    expected_breakeven = 1000.0 * (1 + S.costs.round_trip * 1.15)
    assert pos.stop == pytest.approx(expected_breakeven)

    # precio sube a 1040 (+1.6R >= 1.5R): se activa el trailing stop: max_favorable - 2.0 * atr = 1040 - 20 = 1020
    q2 = Quote(symbol="GGAL", bid=1040.0, ask=1041.0, last=1040.0, volume=100, ts=1010.0)
    exec_analyst.update_position(pos, q2)
    assert pos.stop == pytest.approx(1020.0)


# ---------------------------------------------------------------- integración (simulador)
def test_simulation_runs_and_respects_limits():
    async def run():
        sysm = TradingSystem(S)
        await sysm.start()
        sysm.loop_task.cancel()
        for _ in range(300):
            await sysm.tick()
            if sysm.state.value == "HALTED":
                break
        return sysm
    s = asyncio.run(run())
    snap = s.snapshot()
    assert snap["kpis"]["equity"] > 0
    # nunca superar la exposición máxima
    assert snap["kpis"]["exposure_pct"] <= S.risk.max_total_exposure_pct + 1e-6
    # la pérdida diaria nunca excede el límite + una operación de margen
    assert snap["kpis"]["pnl_pct"] > -(S.risk.daily_max_loss_pct + 0.01)
