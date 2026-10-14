"""Modelos de dominio compartidos por agentes, brokers y orquestador."""
from __future__ import annotations

import itertools
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

_ids = itertools.count(1)


def new_id(prefix: str) -> str:
    return f"{prefix}-{next(_ids):06d}"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[self.value]


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Regime(str, Enum):
    CALM = "CALM"
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    VOLATILE = "VOLATILE"
    CHAOTIC = "CHAOTIC"
    UNCERTAIN = "UNCERTAIN"
    WARMUP = "WARMUP"


class SystemState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"          # sin entradas nuevas, sigue gestionando salidas
    HALTED = "HALTED"          # circuit breaker / kill switch: todo cerrado hasta el día siguiente


@dataclass
class Bar:
    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    volume: float = 0.0
    ts: float = field(default_factory=time.time)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.last

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid else 1.0


@dataclass
class Signal:
    symbol: str
    side: Side
    entry: float
    stop: float
    target: float
    horizon_min: int
    confidence: float
    risk_level: RiskLevel
    risk_score: float
    atr: float
    spread_pct: float
    rationale: List[str] = field(default_factory=list)
    features: Dict[str, float] = field(default_factory=dict)

    @property
    def reward_risk(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risk if risk else 0.0

    @property
    def target_pct(self) -> float:
        return abs(self.target - self.entry) / self.entry


@dataclass
class OrderProposal:
    signal: Signal
    sleeve: str
    quantity: int
    notional: float
    est_round_trip_cost: float
    id: str = field(default_factory=lambda: new_id("PRP"))
    created_at: float = field(default_factory=time.time)
    notes: List[str] = field(default_factory=list)


@dataclass
class Decision:
    proposal_id: str
    symbol: str
    approved: bool
    agent: str
    reasons: List[str]
    adjusted_quantity: Optional[int] = None
    ts: float = field(default_factory=time.time)


@dataclass
class Order:
    symbol: str
    side: Side
    quantity: int
    limit_price: float
    id: str = field(default_factory=lambda: new_id("ORD"))
    status: str = "NEW"          # NEW | FILLED | PARTIAL | CANCELLED | REJECTED
    filled_qty: int = 0
    avg_price: float = 0.0
    fees: float = 0.0
    broker_ref: Optional[str] = None
    reason: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class Position:
    symbol: str
    side: Side
    quantity: int
    entry_price: float
    stop: float
    target: float
    initial_stop: float
    sleeve: str
    risk_level: RiskLevel
    atr: float
    opened_minute: int
    entry_fees: float
    id: str = field(default_factory=lambda: new_id("POS"))
    opened_at: float = field(default_factory=time.time)
    last_price: float = 0.0
    max_favorable: float = 0.0

    @property
    def direction(self) -> int:
        return 1 if self.side == Side.BUY else -1

    @property
    def unrealized_pnl(self) -> float:
        px = self.last_price or self.entry_price
        return (px - self.entry_price) * self.quantity * self.direction

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.initial_stop)
        px = self.last_price or self.entry_price
        return ((px - self.entry_price) * self.direction) / risk if risk else 0.0


@dataclass
class Trade:
    symbol: str
    side: Side
    quantity: int
    entry_price: float
    exit_price: float
    sleeve: str
    risk_level: RiskLevel
    gross_pnl: float
    fees: float
    net_pnl: float
    reason: str
    opened_at: float
    closed_at: float
    held_minutes: int
    id: str = field(default_factory=lambda: new_id("TRD"))


def to_dict(obj: Any) -> Any:
    """Serializa dataclasses/enums a JSON-friendly."""
    if hasattr(obj, "__dataclass_fields__"):
        d = asdict(obj)
        for k, v in d.items():
            d[k] = to_dict(v)
        # agrega propiedades útiles para la UI
        for prop in ("unrealized_pnl", "notional", "r_multiple", "reward_risk", "target_pct"):
            if hasattr(type(obj), prop):
                d[prop] = getattr(obj, prop)
        return d
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    return obj
