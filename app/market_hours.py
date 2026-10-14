"""Calendario y horario del mercado argentino (BYMA)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

try:
    import holidays as _holidays
except ImportError:  # pragma: no cover
    _holidays = None

from .config import MarketHours


@dataclass
class SessionStatus:
    is_trading_day: bool
    is_open: bool
    phase: str                 # PRE_MARKET | OPENING_RISK | CONTINUOUS | CLOSING_RISK | FLATTEN | CLOSED | HOLIDAY | WEEKEND
    entries_allowed: bool
    must_flatten: bool
    now: datetime
    opens_at: Optional[datetime]
    closes_at: Optional[datetime]
    reason: str

    def to_dict(self) -> dict:
        return {
            "is_trading_day": self.is_trading_day,
            "is_open": self.is_open,
            "phase": self.phase,
            "entries_allowed": self.entries_allowed,
            "must_flatten": self.must_flatten,
            "now": self.now.isoformat(),
            "opens_at": self.opens_at.isoformat() if self.opens_at else None,
            "closes_at": self.closes_at.isoformat() if self.closes_at else None,
            "reason": self.reason,
        }


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


class MarketCalendar:
    """Determina si el mercado está abierto y en qué fase de riesgo se encuentra."""

    def __init__(self, cfg: MarketHours):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self._hol_cache: dict[int, object] = {}

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_holiday(self, d: date) -> bool:
        if _holidays is None:
            return False
        if d.year not in self._hol_cache:
            self._hol_cache[d.year] = _holidays.country_holidays("AR", years=d.year)
        return d in self._hol_cache[d.year]  # type: ignore[operator]

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and not self.is_holiday(d)

    def next_open(self, ref: Optional[datetime] = None) -> datetime:
        ref = ref or self.now()
        d = ref.date()
        for _ in range(15):
            o = datetime.combine(d, _parse(self.cfg.open), self.tz)
            if self.is_trading_day(d) and o > ref:
                return o
            d += timedelta(days=1)
        return datetime.combine(d, _parse(self.cfg.open), self.tz)

    def status(self, ref: Optional[datetime] = None) -> SessionStatus:
        now = ref.astimezone(self.tz) if ref else self.now()
        d = now.date()
        opens = datetime.combine(d, _parse(self.cfg.open), self.tz)
        closes = datetime.combine(d, _parse(self.cfg.close), self.tz)

        if d.weekday() >= 5:
            return SessionStatus(False, False, "WEEKEND", False, False, now, self.next_open(now), None, "Fin de semana")
        if self.is_holiday(d):
            return SessionStatus(False, False, "HOLIDAY", False, False, now, self.next_open(now), None, "Feriado nacional")
        if now < opens:
            return SessionStatus(True, False, "PRE_MARKET", False, False, now, opens, closes, "Pre-apertura")
        if now >= closes:
            return SessionStatus(True, False, "CLOSED", False, True, now, self.next_open(now), None, "Mercado cerrado")

        mins_from_open = (now - opens).total_seconds() / 60
        mins_to_close = (closes - now).total_seconds() / 60
        if mins_to_close <= self.cfg.flatten_before_close_min:
            return SessionStatus(True, True, "FLATTEN", False, True, now, opens, closes,
                                 f"Faltan {mins_to_close:.0f} min para el cierre: se cierran posiciones")
        if mins_to_close <= self.cfg.no_entry_before_close_min:
            return SessionStatus(True, True, "CLOSING_RISK", False, False, now, opens, closes,
                                 "Ventana de cierre: alta volatilidad, sin entradas nuevas")
        if mins_from_open < self.cfg.no_entry_after_open_min:
            return SessionStatus(True, True, "OPENING_RISK", False, False, now, opens, closes,
                                 "Ventana de apertura: formación de precio, sin entradas nuevas")
        return SessionStatus(True, True, "CONTINUOUS", True, False, now, opens, closes, "Rueda continua")
