"""Carga y validación de configuración (settings.yaml + .env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class MarketHours(BaseModel):
    timezone: str = "America/Argentina/Buenos_Aires"
    open: str = "10:30"
    close: str = "17:00"
    no_entry_after_open_min: int = 30
    no_entry_before_close_min: int = 30
    flatten_before_close_min: int = 10
    auto_start: bool = True
    ignore_schedule_in_simulation: bool = True


class SleeveCfg(BaseModel):
    weight: float
    allowed_risk: List[Literal["LOW", "MEDIUM", "HIGH"]]
    max_open_positions: int = 3


class Portfolios(BaseModel):
    conservative: SleeveCfg = SleeveCfg(weight=0.8, allowed_risk=["LOW", "MEDIUM"], max_open_positions=2)
    aggressive: SleeveCfg = SleeveCfg(weight=0.2, allowed_risk=["HIGH"], max_open_positions=1)


class RiskCfg(BaseModel):
    risk_per_trade_pct: float = 0.005
    max_position_pct_of_sleeve: float = 0.25
    stop_atr_mult: float = 2.5
    take_profit_rr: float = 2.0
    trailing_atr_mult: float = 2.0
    breakeven_at_r: float = 1.0
    trailing_activation_r: float = 1.5
    min_target_pct: float = 0.015
    max_holding_minutes: int = 60
    min_holding_minutes: int = 15
    daily_max_loss_pct: float = 0.015
    daily_profit_lock_pct: float = 0.03
    max_drawdown_pct: float = 0.03
    max_consecutive_losses: int = 3
    cooldown_minutes_after_losses: int = 15
    symbol_cooldown_minutes: int = 10
    max_trades_per_hour: int = 3
    min_reward_cost_ratio: float = 3.5
    min_reward_risk: float = 1.5
    max_spread_pct: float = 0.006
    max_slippage_pct: float = 0.002
    min_confidence: float = 0.70
    max_total_exposure_pct: float = 0.85


class CostsCfg(BaseModel):
    commission_pct_per_side: float = 0.005
    vat_on_commission: float = 0.21
    market_fees_pct_per_side: float = 0.0008

    @property
    def per_side(self) -> float:
        return self.commission_pct_per_side * (1 + self.vat_on_commission) + self.market_fees_pct_per_side

    @property
    def round_trip(self) -> float:
        return 2 * self.per_side

    def fee(self, notional: float) -> float:
        return abs(notional) * self.per_side


class MoodCfg(BaseModel):
    chaotic_index_z: float = 3.0
    volatile_vol_ratio: float = 1.8
    chaotic_vol_ratio: float = 2.8
    spread_widening_ratio: float = 2.0
    min_breadth_for_longs: float = 0.35
    regime_flip_limit: int = 4


class Instrument(BaseModel):
    symbol: str
    sector: str = "GENERAL"
    static_risk: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    sim_price: float = 1000.0
    sim_vol: float = 0.002


class Settings(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    data_feed: Literal["simulator", "yfinance", "broker"] = "simulator"
    broker: Literal["paper", "iol", "primary"] = "paper"
    capital_ars: float = 1_000_000
    tick_seconds: float = 2
    allow_short: bool = False
    market_hours: MarketHours = MarketHours()
    portfolios: Portfolios = Portfolios()
    risk: RiskCfg = RiskCfg()
    costs: CostsCfg = CostsCfg()
    mood: MoodCfg = MoodCfg()
    universe: List[Instrument] = Field(default_factory=list)

    @property
    def live_allowed_by_env(self) -> bool:
        return os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true"


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.getenv("INVESTMENTS_CONFIG", ROOT / "config" / "settings.yaml"))
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Settings(**raw)
