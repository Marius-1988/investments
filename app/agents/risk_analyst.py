"""Subagente: Analista de Riesgo de la Operación (ventana corta 1-5 minutos)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..indicators import atr, ema, returns, rsi, stdev, vwap, zscore
from ..market_state import MarketState
from ..models import RiskLevel, Side, Signal
from .base import Agent

MIN_BARS = 30


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class ShortTermRiskAnalyst(Agent):
    name = "risk_analyst"
    title = "Analista de Riesgo (1-5 min)"
    mission = ("Medir el riesgo de cada activo en ventana de 1 a 5 minutos, clasificarlo (LOW/MEDIUM/HIGH) "
               "y proponer sólo setups con ventaja estadística después de costos.")
    skills = ["short-term-risk-analyst"]

    # umbrales de volatilidad por minuto (desvío de retornos 1m)
    VOL_LOW = 0.0012
    VOL_HIGH = 0.0028

    def __init__(self, settings, log_fn, static_risk: Dict[str, str]):
        super().__init__(settings, log_fn)
        min_m, max_m = settings.risk.min_holding_minutes, settings.risk.max_holding_minutes
        self.title = f"Analista de Riesgo ({min_m}-{max_m} min)"
        self.mission = (f"Medir el riesgo de cada activo en ventana de {min_m} a {max_m} minutos, clasificarlo (LOW/MEDIUM/HIGH) "
                        "y proponer sólo setups con ventaja estadística después de costos.")
        self.static_risk = {s: RiskLevel(r) for s, r in static_risk.items()}
        self.last_assessments: List[dict] = []

    def _dynamic_level(self, vol: float) -> RiskLevel:
        if vol < self.VOL_LOW:
            return RiskLevel.LOW
        if vol < self.VOL_HIGH:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    def assess(self, symbol: str, market: MarketState) -> Tuple[Optional[dict], Optional[Signal]]:
        bars = list(market.bars[symbol])
        q = market.quotes.get(symbol)
        if len(bars) < MIN_BARS or q is None:
            return None, None
        r = self.settings.risk
        closes = [b.close for b in bars]
        rets = returns(closes[-61:])
        vol = stdev(rets[-30:])
        vol_long = stdev(rets) or vol or 1e-9
        vol_ratio = (stdev(rets[-10:]) / vol_long) if vol_long else 1.0
        a = atr(bars[-16:], 14) or closes[-1] * 0.001
        atr_pct = a / closes[-1]
        static = self.static_risk.get(symbol, RiskLevel.MEDIUM)
        dynamic = self._dynamic_level(vol)
        level = static if static.rank >= dynamic.rank else dynamic   # el más conservador de ambos

        ef, es = ema(closes[-40:], 5), ema(closes[-40:], 20)
        rsi_v = rsi(closes, 14)
        vw = vwap(bars[-60:])
        mom3 = closes[-1] / closes[-4] - 1
        vol_z = zscore(bars[-1].volume, [b.volume for b in bars[-30:-1]])
        spread = q.spread_pct
        stretch = (q.ask - vw) / a if a else 0.0         # cuántos ATR por encima del VWAP (anti-persecución)

        risk_score = (_clamp(vol / 0.004, 0, 1) * 45 + _clamp(spread / r.max_spread_pct, 0, 1) * 20
                      + _clamp((vol_ratio - 1) / 1.5, 0, 1) * 20 + (15 if vol_z < -1 else 0))

        conds = [
            ("Tendencia EMA5 > EMA20", ef > es, 0.22),
            ("Precio sobre VWAP", closes[-1] > vw, 0.18),
            ("RSI en zona de impulso (52-70)", 52 <= rsi_v <= 70, 0.15),
            ("Momentum 3m positivo", mom3 > 0, 0.15),
            ("Volumen acompaña", vol_z > 0, 0.10),
            ("Volatilidad estable", vol_ratio < 1.6, 0.10),
            ("Spread aceptable", spread <= r.max_spread_pct, 0.10),
        ]
        confidence = sum(w for _, ok, w in conds if ok)
        rationale = [("✔ " if ok else "✘ ") + label for label, ok, _ in conds]

        signal: Optional[Signal] = None
        entry = q.ask
        stop = entry - r.stop_atr_mult * a
        min_target_pct = getattr(r, "min_target_pct", 0.015)
        min_target_dist = entry * min_target_pct
        calc_target_dist = r.take_profit_rr * (entry - stop)
        target_dist = max(min_target_dist, calc_target_dist)
        target = entry + target_dist
        target_pct = (target - entry) / entry
        cost = self.settings.costs.round_trip
        edge_vs_cost = target_pct / cost if cost else 99
        # minutos esperados para alcanzar el objetivo (paseo aleatorio): (distancia/ATR)^2, acotado a la ventana
        horizon = int(_clamp(round(((target - entry) / a) ** 2 / 2), r.min_holding_minutes, r.max_holding_minutes))

        if confidence >= r.min_confidence and ef > es and mom3 > 0 and target_pct >= min_target_pct:
            signal = Signal(symbol, Side.BUY, entry, stop, target, horizon, round(confidence, 3), level,
                            round(risk_score, 1), a, spread, rationale,
                            {"rsi": rsi_v, "vol_1m": vol, "vol_ratio": vol_ratio, "atr_pct": atr_pct,
                             "vwap": vw, "stretch_atr": stretch, "mom3": mom3, "vol_z": vol_z,
                             "last_bar_ret": rets[-1] if rets else 0.0})

        opportunity = confidence * min(3.0, edge_vs_cost) / (1 + risk_score / 50) if signal else 0.0
        assessment = {
            "symbol": symbol, "price": q.last, "bid": q.bid, "ask": q.ask,
            "risk_level": level.value, "static_risk": static.value, "dynamic_risk": dynamic.value,
            "risk_score": round(risk_score, 1), "vol_1m_pct": round(vol * 100, 3), "atr_pct": round(atr_pct * 100, 3),
            "spread_pct": round(spread * 100, 3), "rsi": round(rsi_v, 1), "vol_ratio": round(vol_ratio, 2),
            "trend": "UP" if ef > es else "DOWN", "signal": signal.side.value if signal else "—",
            "confidence": round(confidence, 2), "edge_vs_cost": round(edge_vs_cost, 2),
            "opportunity": round(opportunity, 3), "horizon_min": horizon,
        }
        return assessment, signal

    def analyze(self, market: MarketState) -> List[Signal]:
        assessments, signals = [], []
        for s in market.symbols:
            a, sig = self.assess(s, market)
            if a:
                assessments.append(a)
            if sig:
                signals.append((a["opportunity"], sig))
        assessments.sort(key=lambda x: x["opportunity"], reverse=True)
        self.last_assessments = assessments
        signals.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in signals]
